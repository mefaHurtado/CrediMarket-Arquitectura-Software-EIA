'use strict';
const $=id=>document.getElementById(id), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={user:null,token:sessionStorage.getItem('cm_token')||'',products:[],loans:[],clients:[]};
const BASE={p:'/api/productos',c:'/api/clientes',l:'/api/prestamos',i:'/api/inventario'};
const money=n=>new Intl.NumberFormat('es-CO',{style:'currency',currency:'COP',maximumFractionDigits:0}).format(n||0);
function notice(msg,error=false){$('flash').textContent=msg;$('flash').className='active'+(error?' error':'');setTimeout(()=>{$('flash').className='';$('flash').textContent=''},7000)}
async function api(s,path,opt={}){
 const hdr={...(opt.headers||{})};if(state.token)hdr.Authorization='Bearer '+state.token;
 if(opt.body&&!(opt.body instanceof FormData))hdr['Content-Type']='application/json';
 let r;try{r=await fetch(BASE[s]+path,{...opt,headers:hdr})}catch{throw Error('No se pudo conectar con el servidor. Verifica Docker y vuelve a intentar.');}
 let data;try{data=await r.json()}catch{data={detail:'Respuesta del servidor no válida'};}
 if(r.status===401){logout();throw Error(data.detail||'Sesión vencida');}
 if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
 return data;
}
function isAdmin(){return state.user?.role==='admin'}
function logout(){sessionStorage.removeItem('cm_token');state.token='';state.user=null;$('dashboard').hidden=true;$('login').hidden=false;$('who').innerHTML='';}
function logged(){
 $('dashboard').hidden=false;$('login').hidden=true;
 $('who').innerHTML=`<span>${esc(state.user.username)} · ${esc(state.user.role)}</span><button class="secondary" id="logoutBtn">Salir</button>`;
 $('logoutBtn').onclick=logout;$('roleBadge').innerHTML=`<span class="chip">${isAdmin()?'Administración':'Cliente'} · Datos ficticios</span>`;
 document.querySelectorAll('.adm').forEach(x=>x.hidden=!isAdmin());
 showTab('catalogo');refreshProducts();refreshLoans();loadProfile();
}
function showTab(tab){document.querySelectorAll('.tab').forEach(el=>el.hidden=el.id!==tab);document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));if(tab==='solicitudes')refreshLoans();if(tab==='inventario'&&isAdmin())refreshStock();if(tab==='modelo'&&isAdmin())refreshModel();if(tab==='perfil')loadProfile();}
async function refreshProducts(){try{
 state.products=await api('p','/productos');
 $('productsList').innerHTML=state.products.map(p=>`<div class="product"><span class="chip">${esc(p.category)}</span><h3>${esc(p.name)}</h3><small>Versión ${esc(p.version)} · ID ${esc(p.id.slice(0,8))}…</small><div class="price">${money(p.price)}</div><button class="secondary" data-product="${esc(p.id)}">Seleccionar</button></div>`).join('')||'No hay productos';
 for(const id of ['loanProduct','stockProduct'])$(id).innerHTML=state.products.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
 document.querySelectorAll('[data-product]').forEach(b=>b.onclick=()=>{$('loanProduct').value=b.dataset.product;document.querySelector('#loanForm input[name=cantidad]').focus()});
 }catch(e){notice(e.message,true)}}
async function refreshLoans(){if(!state.user)return;try{
 state.loans=await api('l','/prestamos');$('loansList').innerHTML=state.loans.map(l=>`<tr><td title="${esc(l.id)}">${esc(l.id.slice(0,8))}…<br><small>${esc(l.modelo)} · precio v${esc(l.version_precio)}</small></td><td><span class="state ${esc(l.estado)}">${esc(l.estado)}</span><br><small>${esc(l.motivo||'')}</small></td><td>${money(l.monto)}</td><td>${(l.probabilidad_incumplimiento*100).toFixed(1)}%<br><small>umbral ${(l.umbral*100).toFixed(1)}%</small></td><td>${esc(l.producto_id.slice(0,8))}…</td><td>${['APROBADA','PENDIENTE_INVENTARIO'].includes(l.estado)?`<button class="danger" data-cancel="${esc(l.id)}">Cancelar</button>`:''}${l.estado==='APROBADA'&&isAdmin()?`<button data-deliver="${esc(l.id)}">Entregar</button>`:''}</td></tr>`).join('')||'<tr><td colspan="6">Aún no hay solicitudes</td></tr>';
 document.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async()=>{try{await api('l','/prestamos/'+b.dataset.cancel+'/cancelar',{method:'POST'});notice('Cancelación iniciada; espera confirmación de liberación');refreshLoans()}catch(e){notice(e.message,true)}});
 document.querySelectorAll('[data-deliver]').forEach(b=>b.onclick=async()=>{try{await api('l','/prestamos/'+b.dataset.deliver+'/entregar',{method:'POST'});notice('Orden de entrega enviada a Inventario');refreshLoans()}catch(e){notice(e.message,true)}});
 }catch(e){notice(e.message,true)}}
async function loadProfile(){if(!state.user)return;try{
 if(isAdmin()){state.clients=await api('c','/clientes');$('clientsList').innerHTML=state.clients.slice(0,50).map(x=>`<div><b>${esc(x.name)}</b> · ${money(x.income)}<br><span>${esc(x.id)}</span><button class="secondary" data-client="${esc(x.id)}">Editar</button></div>`).join('');document.querySelectorAll('[data-client]').forEach(b=>b.onclick=()=>setProfile(state.clients.find(c=>c.id===b.dataset.client)));}
 else{const profile=await api('c','/clientes/'+state.user.client_id);setProfile(profile);document.querySelector('#customerForm input[name=id]').readOnly=true;}
 }catch(e){notice(e.message,true)}}
function setProfile(c){if(!c)return;const f=$('customerForm');for(const k of ['id','name','income','obligations','employment','tenure','history','previous','arrears','punctual']){if(f.elements[k])f.elements[k].value=c[k]??''}}
async function refreshStock(){try{
 const [stock,res,moves]=await Promise.all([api('i','/inventario'),api('i','/inventario/reservas'),api('i','/inventario/movimientos')]);
 $('stockList').innerHTML=stock.map(x=>`<div class="product"><b>${esc(state.products.find(p=>p.id===x.product_id)?.name||x.product_id)}</b><p>Totales: ${x.quantity} · Reservadas: ${x.reserved} · Disponibles: <b>${x.available}</b></p></div>`).join('');
 $('reservationsList').innerHTML='<h4>Últimas reservas</h4>'+res.slice(0,12).map(x=>`<div class="list"><div>${esc(x.prestamo_id.slice(0,8))}… · ${esc(x.estado)} · ${x.cantidad} unidades</div></div>`).join('');
 $('movementsList').innerHTML='<h4>Movimientos</h4>'+moves.slice(0,12).map(x=>`<div class="list"><div>${esc(x.tipo)} · ${x.unidades} · ${esc(x.producto_id.slice(0,8))}…</div></div>`).join('');
 }catch(e){notice(e.message,true)}}
async function refreshModel(){try{
 const [m,monitor]=await Promise.all([api('l','/modelo/info'),api('l','/modelo/monitor')]);
 $('modelInfo').textContent=JSON.stringify(m,null,2);$('monitorInfo').textContent=JSON.stringify(monitor,null,2);$('modelVersion').value=m.model_version;
 }catch(e){notice(e.message,true)}}
function payload(form){return Object.fromEntries(new FormData(form).entries())}
$('loginForm').onsubmit=async e=>{e.preventDefault();let f=payload(e.target);try{let a=await api('c','/auth/login',{method:'POST',body:JSON.stringify(f)});state.user={username:a.username,role:a.role,client_id:a.client_id};state.token=a.access_token;sessionStorage.setItem('cm_token',a.access_token);logged()}catch(err){alert(err.message)}};
$('loanForm').onsubmit=async e=>{e.preventDefault();const b=payload(e.target);b.cantidad=Number(b.cantidad);b.plazo_meses=Number(b.plazo_meses);const fingerprint=JSON.stringify(b);let attempt=JSON.parse(sessionStorage.getItem('cm_attempt')||'null');const key=attempt?.fingerprint===fingerprint?attempt.key:crypto.randomUUID();sessionStorage.setItem('cm_attempt',JSON.stringify({fingerprint,key}));e.submitter.disabled=true;try{
 const l=await api('l','/prestamos',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(b)});sessionStorage.removeItem('cm_attempt');notice('Solicitud registrada: '+l.id+' · estado: '+l.estado);showTab('solicitudes');
 }catch(err){notice(err.message+'; vuelve a intentar con la misma operación cuando corresponda.',true)}finally{e.submitter.disabled=false}};
$('productForm').onsubmit=async e=>{e.preventDefault();const b=payload(e.target);const id=b.id;delete b.id;b.price=Number(b.price);try{await api('p',id?'/productos/'+id:'/productos',{method:id?'PUT':'POST',body:JSON.stringify(b)});notice('Producto guardado');refreshProducts()}catch(err){notice(err.message,true)}};
$('deactivateProduct').onclick=async()=>{const id=$('productForm').elements.id.value;if(!id)return notice('Indica el ID del producto',true);if(!confirm('¿Desactivar producto?'))return;try{await api('p','/productos/'+id,{method:'DELETE'});notice('Producto desactivado');refreshProducts()}catch(e){notice(e.message,true)}};
$('customerForm').onsubmit=async e=>{e.preventDefault();const b=payload(e.target);const id=b.id;delete b.id;for(const k of ['income','obligations','previous','arrears'])b[k]=Number(b[k]);for(const k of ['tenure','history','punctual'])b[k]=b[k]===''?null:Number(b[k]);try{if(!isAdmin()&&!id)throw Error('No existe un cliente asignado');await api('c',id?'/clientes/'+id:'/clientes',{method:id?'PUT':'POST',body:JSON.stringify(b)});notice('Datos del cliente guardados');loadProfile()}catch(err){notice(err.message,true)}};
$('csvForm').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);try{const res=await api('c','/clientes/importar',{method:'POST',body:f});$('importResult').textContent=JSON.stringify(res,null,2);notice('Importación terminada');loadProfile()}catch(err){notice(err.message,true)}};
$('stockForm').onsubmit=async e=>{e.preventDefault();const b=payload(e.target);b.units=Number(b.units);try{await api('i','/inventario/entradas',{method:'POST',body:JSON.stringify(b)});notice('Entrada de inventario persistida');refreshStock()}catch(err){notice(err.message,true)}};
$('promoteModel').onclick=async()=>{try{await api('l','/modelo/activar',{method:'POST',body:JSON.stringify({version:$('modelVersion').value})});notice('Modelo promovido: '+$('modelVersion').value);refreshModel()}catch(e){notice(e.message,true)}};
$('cacheMetrics').onclick=async()=>{try{$('redisInfo').textContent=JSON.stringify(await api('p','/metrics/cache'),null,2)}catch(e){notice(e.message,true)}};
$('refreshProducts').onclick=refreshProducts;$('refreshLoans').onclick=refreshLoans;$('refreshClients').onclick=loadProfile;$('refreshStock').onclick=refreshStock;$('refreshModel').onclick=refreshModel;
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
setInterval(()=>{if(state.user&&$('solicitudes').hidden===false)refreshLoans()},3000);
(async()=>{if(state.token){try{const me=await api('c','/auth/me');state.user={username:'Sesión restaurada',role:me.role,client_id:me.client_id};logged()}catch{logout()}}})();
