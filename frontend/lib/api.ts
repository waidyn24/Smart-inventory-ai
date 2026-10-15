export const BASE=process.env.NEXT_PUBLIC_API_URL||'/api';
export async function api(path:string,options:RequestInit={}){
 const isForm=options.body instanceof FormData;
 const r=await fetch(`${BASE}${path}`,{...options,credentials:'include',cache:'no-store',headers:{...(isForm?{}:{'Content-Type':'application/json'}),...((options.method||'GET')==='GET'?{}:{'X-CSRF-Token':typeof window==='undefined'?'':sessionStorage.getItem('siai_csrf')||''}),...options.headers}});
 if(!r.ok){let detail='Ошибка запроса';try{const d=await r.json();detail=typeof d.detail==='string'?d.detail:JSON.stringify(d.detail)}catch{}if(r.status===401&&typeof window!=='undefined'&&!window.location.pathname.startsWith('/login'))window.location.href='/login';throw new Error(detail)}
 if(r.headers.get('content-type')?.includes('application/json'))return r.json();return r.blob();
}
export const cash=(n:number|string)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(Number(n)||0)+' ₸';
export const num=(n:number|string,d=0)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(Number(n)||0);
export const dt=(s:string)=>new Date(s).toLocaleDateString('ru-RU',{timeZone:'Asia/Almaty',day:'2-digit',month:'2-digit',year:'numeric'});
export const newKey=()=>crypto.randomUUID();
export type Product={id:string,name:string,sku:string,barcode:string,category:string,unit:string,price:number,cost:number,supplier_id:string|null,min_order_qty:number,pack_multiple:number,shelf_life_days:number|null,min_stock:number,active:boolean,on_hand:number,available:number};
export type Supplier={id:string,name:string,phone:string,lead_time_days:number};
export type Rec={product_id:string,name:string,sku:string,quantity:number,daily_demand:number,days_to_stockout:number|null,stock:number,estimated_cost:number,supplier_id:string|null,supplier_name:string|null,urgency:string,reason:string,pack_multiple:number,min_order_qty:number,unit_cost:number,inventory_position:number,safety_stock:number,target_stock:number,lead_time_days:number,certainty:string,constraints:string[]};
