/* Avisos de pedidos para empleados con permiso. Solo se consultan contadores.
   Las notificaciones fuera de la app requieren activar Web Push. */
(() => {
  const conf=document.getElementById('config-avisos-admin');
  if(!conf) return;
  const badge=document.getElementById('aviso-pendientes-nav');
  const activar=document.getElementById('activar-alertas');
  const desactivar=document.getElementById('desactivar-alertas');
  const estado=document.getElementById('estado-alertas');
  const clave=conf.dataset.clave;
  const store='pa-picar-ultimo-pedido:'+conf.dataset.usuario;
  const guardado=sessionStorage.getItem(store);
  let ultimoVisto=guardado===null?null:Number(guardado)||0;
  function convertirClave(k){
    const b=k.replace(/-/g,'+').replace(/_/g,'/');
    const s=atob(b.padEnd(Math.ceil(b.length/4)*4,'='));
    return Uint8Array.from(s,c=>c.charCodeAt(0));
  }
  async function consultar(){
    try{
      const respuesta=await fetch(conf.dataset.estado,{cache:'no-store',credentials:'same-origin'});
      if(!respuesta.ok) return;
      const datos=await respuesta.json();
      const pendientes=Number(datos.pendientes)||0;
      const id=Number(datos.ultimo_id)||0;
      badge.hidden=pendientes===0;
      badge.textContent=pendientes>99?'99+':String(pendientes);
      if(ultimoVisto!==null && id>ultimoVisto) {
        const alerta=document.createElement('div');
        alerta.className='aviso-flotante-nuevo';
        alerta.setAttribute('role','status');
        const link=document.createElement('a');
        link.href='/pedidos?estado=Pendiente';
        link.textContent='¡Nuevo pedido #'+id+'! Revisar pedidos';
        alerta.append(link);
        document.body.append(alerta);
        setTimeout(()=>alerta.remove(),9000);
      }
      ultimoVisto=Math.max(ultimoVisto||0,id);
      sessionStorage.setItem(store,String(ultimoVisto));
      if('setAppBadge' in navigator) {
        pendientes?navigator.setAppBadge(pendientes).catch(()=>{}):
                   navigator.clearAppBadge().catch(()=>{});
      }
    }catch(err){/* No interrumpe la administración sin conexión. */}
  }
  consultar();
  setInterval(consultar,20000);
  if(!activar||!desactivar||!estado)return;
  const compatible='Notification' in window && 'serviceWorker' in navigator &&
                   'PushManager' in window && Boolean(clave);
  const esIphone=/iPad|iPhone|iPod/i.test(navigator.userAgent);
  const appInstalada=window.navigator.standalone===true ||
                     window.matchMedia('(display-mode: standalone)').matches;
  const mensajeInstalacion='En iPhone, abre Pa Picar desde el ícono de la pantalla de inicio para activar notificaciones. Si estás en Safari, usa Compartir → Agregar a Inicio.';
  async function registrarEnPaPicar(sub){
    const resp=await fetch(conf.dataset.suscribir,{
      method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({csrf:conf.dataset.token,subscription:sub.toJSON()})
    });
    if(!resp.ok)throw new Error('No se pudo confirmar el registro del dispositivo.');
  }
  async function sincronizar(){
    if(esIphone && !appInstalada){
      estado.textContent=mensajeInstalacion;
      activar.hidden=true;
      desactivar.hidden=true;
      return;
    }
    if(!compatible){
      estado.textContent='Este navegador no permite notificaciones web aquí. En un iPhone compatible, usa la aplicación instalada desde Safari.';
      activar.hidden=true;
      desactivar.hidden=true;
      return;
    }
    if(Notification.permission==='denied'){
      estado.textContent='Las notificaciones están bloqueadas para esta aplicación. Revísalas en Ajustes de tu iPhone.';
      activar.hidden=true;
      desactivar.hidden=true;
      return;
    }
    activar.hidden=false;
    activar.textContent='Activar notificaciones';
    desactivar.hidden=true;
    if(Notification.permission!=='granted'){
      estado.textContent='Avisos no activados. Pulsa Activar notificaciones y acepta el permiso.';
      return;
    }
    // Si el navegador ya tenía permiso, comprobar y registrar la suscripción
    // que pudo haber quedado solo en el iPhone por un fallo anterior de guardado.
    try {
      const registro=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
      const sub=await registro.pushManager.getSubscription();
      if(sub) {
        activar.textContent='Confirmar registro de notificaciones';
        estado.textContent='Permiso concedido. Comprobando el registro de Pa Picar…';
        try {
          await registrarEnPaPicar(sub);
          activar.hidden=true;
          desactivar.hidden=false;
          estado.textContent='Notificaciones activadas para esta cuenta en este dispositivo.';
        } catch(err) {
          estado.textContent='El permiso está concedido, pero falta registrar tu iPhone. Pulsa Confirmar registro.';
        }
      } else {
        estado.textContent='El iPhone tiene permiso, pero aún no está suscrito. Pulsa Activar notificaciones.';
      }
    }catch(err) {
      estado.textContent='No se pudo preparar el dispositivo. Abre Pa Picar desde la pantalla de inicio e inténtalo de nuevo.';
    }
  }
  sincronizar();
  activar.addEventListener('click',async()=>{
    // Solicitar permiso justo desde el toque del usuario.
    const permisoPendiente=Notification.requestPermission();
    activar.disabled=true;
    try{
      const permiso=await permisoPendiente;
      if(permiso!=='granted'){estado.textContent='Permiso denegado. Seguirás viendo el contador de pedidos.';return;}
      const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
      let sub=await reg.pushManager.getSubscription();
      if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:convertirClave(clave)});
      await registrarEnPaPicar(sub);
      activar.hidden=true;
      desactivar.hidden=false;
      estado.textContent='Notificaciones activadas para esta cuenta en este dispositivo.';
    }catch(err){estado.textContent='No se pudieron activar los avisos. Puedes seguir usando el panel.';}
    finally{activar.disabled=false;}
  });
  desactivar.addEventListener('click',async()=>{
    try{
      const reg=await navigator.serviceWorker.ready;
      const sub=await reg.pushManager.getSubscription();
      if(sub){
        const resp=await fetch(conf.dataset.desactivar,{
          method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({csrf:conf.dataset.token,endpoint:sub.endpoint})
        });
        if(!resp.ok)throw new Error('No guardado');
        await sub.unsubscribe();
      }
      estado.textContent='Avisos del dispositivo desactivados.';
      activar.hidden=false;
      desactivar.hidden=true;
      estado.textContent='Avisos del dispositivo desactivados.';
    }catch(err){estado.textContent='No se pudo desactivar el aviso. Inténtalo de nuevo.';}
  });
})();
