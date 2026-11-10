"""RabbitMQ: publicación confirmada, outbox durable, reintentos acotados y DLQ."""
import os, json, time, threading, logging
import pika
from .core import Outbox, Inbox
log=logging.getLogger(__name__)
EX='credimarket.events'; RET='credimarket.retry'; DEAD='credimarket.dead'
KEYS={'inventory':['reserva.solicitada','reserva.liberar','reserva.confirmar'],
      'loans':['inventario.reservado','inventario.insuficiente','inventario.liberado','inventario.entregado','inventario.expirado']}

def connect():
    params=pika.URLParameters(os.environ['RABBITMQ_URL']); params.socket_timeout=5
    params.heartbeat=30; params.blocked_connection_timeout=8
    return pika.BlockingConnection(params)

def topology(ch):
    ch.exchange_declare(exchange=EX,exchange_type='direct',durable=True)
    ch.exchange_declare(exchange=RET,exchange_type='direct',durable=True)
    ch.exchange_declare(exchange=DEAD,exchange_type='direct',durable=True)
    for service, keys in KEYS.items():
        ch.queue_declare(queue=service+'.commands',durable=True,arguments={'x-dead-letter-exchange':RET})
        ch.queue_declare(queue=service+'.retry',durable=True,arguments={'x-message-ttl':3000,'x-dead-letter-exchange':EX})
        ch.queue_declare(queue=service+'.dead',durable=True)
        ch.queue_bind(queue=service+'.dead',exchange=DEAD,routing_key=service)
        for key in keys:
            ch.queue_bind(queue=service+'.commands',exchange=EX,routing_key=key)
            ch.queue_bind(queue=service+'.retry',exchange=RET,routing_key=key)

def publish(ch, exchange, routing, data):
    props=pika.BasicProperties(delivery_mode=2,content_type='application/json',
        message_id=data.get('event_id'),correlation_id=data.get('correlation_id'))
    ok=ch.basic_publish(exchange=exchange,routing_key=routing,body=json.dumps(data).encode(),properties=props,mandatory=True)
    if ok is False: raise RuntimeError('Broker no confirmó la publicación')

def outbox_loop(Session,stop=None):
    stop=stop or threading.Event()
    while not stop.is_set():
        con=None
        try:
            con=connect(); ch=con.channel();topology(ch);ch.confirm_delivery()
            while not stop.is_set():
                with Session() as db:
                    rows=db.query(Outbox).filter(Outbox.sent==False).order_by(Outbox.created).limit(50).all()
                    for rec in rows:
                        # Confirmar con RabbitMQ antes de marcar enviado. Si se duplica, inbox tolera la reentrega.
                        publish(ch,EX,rec.route,json.loads(rec.body))
                        rec.sent=True
                        db.commit()
                stop.wait(1)
        except Exception as ex:
            log.warning('Outbox sin conexión: %s',ex)
            stop.wait(3)
        finally:
            if con and con.is_open:
                try: con.close()
                except Exception: pass

def consume_loop(service,Session,handler):
    """handler(db,msg) ejecuta cambios locales; la inserción inbox y commit es única transacción."""
    while True:
        con=None
        try:
            con=connect();ch=con.channel();topology(ch);ch.confirm_delivery();ch.basic_qos(prefetch_count=1)
            q=service+'.commands'
            def callback(channel,method,properties,body):
                try:
                    data=json.loads(body); eid=data['event_id']
                    with Session() as db:
                        if not db.get(Inbox,eid):
                            handler(db,data)
                            db.add(Inbox(event_id=eid))
                            db.commit()
                    channel.basic_ack(method.delivery_tag)
                except Exception as ex:
                    log.exception('Error procesando %s: %s',service,ex)
                    deaths=(method.routing_key,)
                    hist=(properties.headers or {}).get('x-death',[])
                    attempts=sum(int(x.get('count',0)) for x in hist if x.get('queue')==q)
                    if attempts >= 3:
                        try:
                            raw=json.loads(body);raw['_dead_reason']=str(ex)[:200]
                            publish(ch,DEAD,service,raw)
                            channel.basic_ack(method.delivery_tag)
                        except Exception: channel.basic_nack(method.delivery_tag,requeue=True)
                    else:
                        channel.basic_nack(method.delivery_tag,requeue=False)
            ch.basic_consume(queue=q,on_message_callback=callback,auto_ack=False)
            ch.start_consuming()
        except Exception as ex:
            log.warning('Consumidor %s reconectando: %s',service,ex)
            time.sleep(3)
        finally:
            if con and con.is_open:
                try: con.close()
                except Exception: pass
