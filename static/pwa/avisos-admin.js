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
  let ultimoVisto=Number(sessionStorage.getItem(store))||0;
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
      if(ultimoVisto && id>ultimoVisto) {
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
      ultimoVisto=Math.max(ultimoVisto,id);
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
  async function sincronizar(){
    if(!compatible) {
      estado.textContent='Las alertas del sistema requieren una app PWA compatible.';
      return;
    }
    try{
      const reg=await navigator.serviceWorker.ready;
      const sub=await reg.pushManager.getSubscription();
      desactivar.hidden=!(sub&&Notification.permission==='granted');
      activar.hidden=Boolean(sub&&Notification.permission==='granted');
    }catch(err){activar.hidden=false;desactivar.hidden=true;}
  }
  if(compatible) {
    activar.hidden=false;
    sincronizar();
  }
  activar.addEventListener('click',async()=>{
    // Solicitar permiso justo desde el toque del usuario.
    const permisoPendiente=Notification.requestPermission();
    activar.disabled=true;
    try{
      const permiso=await permisoPendiente;
      if(permiso!=='granted'){estado.textContent='Permiso denegado. Seguirás viendo el contador de pedidos.';return;}
      const reg=await navigator.serviceWorker.ready;
      let sub=await reg.pushManager.getSubscription();
      if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:convertirClave(clave)});
      const resp=await fetch(conf.dataset.suscribir,{
        method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({csrf:conf.dataset.token,subscription:sub.toJSON()})
      });
      if(!resp.ok)throw new Error('No se pudo guardar la suscripción');
      estado.textContent='Notificaciones activadas para esta cuenta en este dispositivo.';
      await sincronizar();
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
      await sincronizar();
    }catch(err){estado.textContent='No se pudo desactivar el aviso. Inténtalo de nuevo.';}
  });
})();
