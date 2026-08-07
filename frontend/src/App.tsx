import { FormEvent, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Work = {
  id: number; kind: "comic" | "illustration"; fileName: string;
  number: string | null; title: string; rating: number;
  tags: { id: number; name: string; groupId?:number|null; groupName?:string|null }[];
};
type WorkPage = { items: Work[]; total: number; page: number; pages: number };
type Detail = Work & { fingerprint: string; previews: string[]; coverMember:string|null };
type Tag = { id: number; name: string; rawName?:string;groupId?:number|null;groupName?:string|null;works?:number };

const tokenKey = `hlibrary-token:${location.host}`;
const computersKey = "hlibrary-computer-entries";

function savedComputers(): string[] {
  try { return JSON.parse(localStorage.getItem(computersKey) ?? "[]") as string[]; }
  catch { return []; }
}

function rememberComputer(value: string) {
  const url = new URL(value, location.href).origin;
  localStorage.setItem(computersKey, JSON.stringify([...new Set([url, ...savedComputers()])].slice(0, 20)));
  return url;
}

async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...init?.headers },
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "请求失败");
  return response.json() as Promise<T>;
}

function Pair({ onPaired }: { onPaired: (token: string) => void }) {
  const nonce = new URLSearchParams(location.search).get("pair") ?? "";
  const [code, setCode] = useState("");
  const [name, setName] = useState("我的手机");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    try {
      const result = await api<{ token: string }>("/api/pair", "", {
        method: "POST", body: JSON.stringify({ code, nonce, name }), headers: { Authorization: "" },
      });
      localStorage.setItem(tokenKey, result.token); onPaired(result.token);
      rememberComputer(location.origin);
      history.replaceState(null, "", location.pathname);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "配对失败"); }
  }
  return <main className="center"><form className="panel" onSubmit={submit}>
    <span className="eyebrow">首次连接</span><h1>H库</h1>
    {!nonce && <p className="error">请扫描 Windows 配对页面中的二维码进入。</p>}
    <label>设备名称<input value={name} onChange={e => setName(e.target.value)} /></label>
    <label>六位配对码<input inputMode="numeric" maxLength={6} value={code} onChange={e => setCode(e.target.value)} /></label>
    {error && <p className="error">{error}</p>}<button disabled={!nonce || code.length !== 6}>配对</button>
  </form></main>;
}

function AuthImage({ path, token }: { path: string; token: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => { let current = ""; fetch(path, { headers: { Authorization: `Bearer ${token}` } })
    .then(response => response.ok ? response.blob() : Promise.reject())
    .then(blob => { current = URL.createObjectURL(blob); setUrl(current); }).catch(() => setUrl(""));
    return () => { if (current) URL.revokeObjectURL(current); }; }, [path, token]);
  return url ? <img src={url} alt="封面" /> : <div className="cover-placeholder">无封面</div>;
}

function CoverSelector({id,token,current,choose,close}:{id:number;token:string;current:string|null;choose:(member:string)=>void;close:()=>void}){
  const pages=useQuery({queryKey:["cover-pages",id],queryFn:()=>api<{items:string[]}>(`/api/works/${id}/pages`,token)});const [index,setIndex]=useState(0);
  useEffect(()=>{const found=pages.data?.items.indexOf(current??"001.webp")??-1;if(found>=0)setIndex(found)},[pages.data,current]);
  const count=pages.data?.items.length??0;
  return <div className="modal"><section className="panel"><h2>选择封面</h2>{count>0&&<div className="detail-cover"><AuthImage path={`/api/works/${id}/pages/${index}`} token={token}/></div>}<p>{index+1}/{count} · {pages.data?.items[index]}</p><div className="modal-actions"><button onClick={()=>setIndex(Math.max(0,index-1))}>上一张</button><button onClick={()=>setIndex(Math.min(count-1,index+1))}>下一张</button><button className="quiet" onClick={close}>取消</button><button onClick={()=>{const member=pages.data?.items[index];if(member)choose(member)}}>设为封面</button></div></section></div>;
}

function PreviewStrip({id,token,members}:{id:number;token:string;members:string[]}){
  const [large,setLarge]=useState<number|null>(null);const timer=useRef<number|undefined>(undefined);const start=useRef(0);
  function down(index:number,event:React.PointerEvent){start.current=event.clientX;timer.current=window.setTimeout(()=>setLarge(index),500)}
  function move(event:React.PointerEvent){if(Math.abs(event.clientX-start.current)>10)clearTimeout(timer.current)}
  function up(){clearTimeout(timer.current);setLarge(null)}
  return <><div className="preview-strip">{members.map((member,index)=><div key={member} onPointerDown={event=>down(index,event)} onPointerMove={move} onPointerUp={up} onPointerCancel={up}><AuthImage path={`/api/works/${id}/previews/${index}`} token={token}/></div>)}</div>{large!==null&&<div className="preview-large" onPointerUp={up} onPointerCancel={up}><AuthImage path={`/api/works/${id}/previews/${large}`} token={token}/></div>}</>;
}

function DetailView({ id, token, back, read }: { id: number; token: string; back: () => void; read: () => void }) {
  const detail = useQuery({ queryKey: ["detail", id], queryFn: () => api<Detail>(`/api/works/${id}`, token) });
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<Tag[]>("/api/tags", token) });
  const [editing, setEditing] = useState(false); const [title, setTitle] = useState(""); const [rating, setRating] = useState(0); const [selectedTags, setSelectedTags] = useState<number[]>([]);const [tagSearch,setTagSearch]=useState("");const [cover,setCover]=useState<string|null>(null);const [coverOpen,setCoverOpen]=useState(false);
  useEffect(() => { if (detail.data) { setTitle(detail.data.title); setRating(detail.data.rating); setSelectedTags(detail.data.tags.map(tag => tag.id));setCover(detail.data.coverMember); } }, [detail.data]);
  if (!detail.data) return <main className="library"><button onClick={back}>返回</button><p>正在载入详情…</p></main>;
  const work = detail.data;
  function cancelEdit(){setTitle(work.title);setRating(work.rating);setSelectedTags(work.tags.map(tag=>tag.id));setCover(work.coverMember);setEditing(false)}
  async function save() { await api(`/api/works/${id}`, token, { method:"PUT", body:JSON.stringify({ title, rating, tag_ids:selectedTags, cover_member:cover }) }); setEditing(false); await detail.refetch(); }
  return <main className="library detail"><header><button className="quiet" onClick={()=>editing?(confirm("放弃本次未保存修改？")&&back()):back()}>返回</button><button onClick={()=>editing?cancelEdit():setEditing(true)}>{editing?"取消":"编辑"}</button></header>
    <div className="detail-cover"><AuthImage path={`/api/works/${id}/thumbnail`} token={token}/></div>
    {editing ? <section className="panel edit"><label>标题<input value={title} onChange={e=>setTitle(e.target.value)}/></label><label>星级<select value={rating} onChange={e=>setRating(Number(e.target.value))}>{[0,1,2,3].map(v=><option key={v}>{v}</option>)}</select></label><input placeholder="搜索 Tag 或隐藏分组" value={tagSearch} onChange={e=>setTagSearch(e.target.value)}/><div className="tag-grid">{tags.data?.filter(tag=>tag.name.toLocaleLowerCase().includes(tagSearch.trim().toLocaleLowerCase())).map(tag=><button title={tag.name} className={selectedTags.includes(tag.id)?"selected":"quiet"} key={tag.id} onClick={()=>setSelectedTags(values=>values.includes(tag.id)?values.filter(v=>v!==tag.id):[...values,tag.id])}>{tag.name}</button>)}</div>{work.kind==="comic"&&<button onClick={()=>setCoverOpen(true)}>更改封面</button>}<button className="detail-primary" onClick={save}>保存</button></section> : <><h1>{work.title}</h1><p>{work.kind==="comic"?work.number:work.fileName}</p><p className="stars">{"★".repeat(work.rating)}{"☆".repeat(3-work.rating)}</p><div className="tags detail-tags"><span className="system-tag">{work.kind==="comic"?"漫画":"插画"}</span>{work.tags.map(tag=><span className={tag.groupId==null?"ungrouped":""} key={tag.id}>{tag.name}</span>)}</div>{work.kind==="comic"&&<><PreviewStrip id={id} token={token} members={work.previews}/><button className="detail-primary" onClick={read}>开始阅读</button></>}</>}{coverOpen&&<CoverSelector id={id} token={token} current={cover} close={()=>setCoverOpen(false)} choose={member=>{setCover(member);setCoverOpen(false)}}/>}
  </main>;
}

function MobileReader({ id, token, back }: { id:number; token:string; back:()=>void }) {
  const pages = useQuery({ queryKey:["pages",id], queryFn:()=>api<{items:string[];fingerprint:string}>(`/api/works/${id}/pages`,token) });
  const progress = useQuery({ queryKey:["progress",id], queryFn:()=>api<{pageIndex:number;pageOffset:number;hasProgress:boolean;fingerprint:string}>(`/api/works/${id}/progress`,token) });
  const [urls,setUrls]=useState<string[]>([]); const [index,setIndex]=useState(0); const [mode,setMode]=useState(()=>localStorage.getItem("hlibrary-reader-mode")??"continuous"); const [tools,setTools]=useState(true); const [resume,setResume]=useState(true);
  const [zoom,setZoom]=useState(1);const currentPosition=useRef({index:0,offset:0});
  useEffect(()=>{if(!pages.data)return;let cancelled=false;const made:string[]=[];const cacheName=`hlibrary-session-${id}-${pages.data.fingerprint}`;async function download(retried=false){try{const cache="caches" in window?await caches.open(cacheName):null;for(let i=0;i<(pages.data?.items.length??0)&&!cancelled;i++){const path=`/api/works/${id}/pages/${i}`;const response=await fetch(path,{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw new Error("页面下载失败");if(cache)await cache.put(new Request(path),response.clone());const url=URL.createObjectURL(await response.blob());made.push(url);if(!cancelled)setUrls([...made])}}catch{made.splice(0).forEach(URL.revokeObjectURL);setUrls([]);if("caches" in window)await caches.delete(cacheName);if(!retried&&!cancelled)await download(true);else if(!cancelled)alert("手机存储空间不足，断网阅读不可用，将继续在线读取。")}}void download();return()=>{cancelled=true;made.forEach(URL.revokeObjectURL);if("caches" in window)void caches.delete(cacheName)}},[pages.data,id,token]);
  useEffect(()=>{const timer=setTimeout(()=>setResume(false),5000);return()=>clearTimeout(timer)},[]);
  useEffect(()=>{if(!tools)return;const timer=setTimeout(()=>setTools(false),5000);return()=>clearTimeout(timer)},[tools,index,mode]);
  useEffect(()=>{const key=`hlibrary-pending-progress:${location.host}:${id}`;async function sync(){const pending=localStorage.getItem(key);if(!pending)return;try{await api(`/api/works/${id}/progress`,token,{method:"PUT",body:pending});localStorage.removeItem(key)}catch{/* keep until this computer is reachable */}}window.addEventListener("online",sync);void sync();return()=>window.removeEventListener("online",sync)},[id,token]);
  useEffect(()=>{if(mode!=="continuous"||!pages.data)return;const observer=new IntersectionObserver(entries=>{const visible=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(!visible)return;const target=visible.target as HTMLElement;const next=Number(target.dataset.page);const rect=target.getBoundingClientRect();const offset=Math.min(10000,Math.max(0,Math.round(-rect.top/Math.max(1,rect.height)*10000)));currentPosition.current={index:next,offset};setIndex(next)},{threshold:[.25,.5,.75]});document.querySelectorAll(".continuous-pages img").forEach(image=>observer.observe(image));return()=>observer.disconnect()},[mode,urls,pages.data]);
  function save(next:number){currentPosition.current={index:next,offset:0};setIndex(next)}
  async function exitReader(){if(pages.data){const position=currentPosition.current;const body=JSON.stringify({page_index:position.index,page_offset:position.offset,fingerprint:pages.data.fingerprint});const key=`hlibrary-pending-progress:${location.host}:${id}`;localStorage.setItem(key,body);try{await api(`/api/works/${id}/progress`,token,{method:"PUT",body});localStorage.removeItem(key)}catch{/* keep the exit position until this computer is reachable */}}back()}
  function jump(next:number){save(next);if(mode==="continuous")requestAnimationFrame(()=>document.querySelector(`[data-page="${next}"]`)?.scrollIntoView())}
  function tap(event:React.MouseEvent){const box=event.currentTarget.getBoundingClientRect();const x=event.clientX-box.left,y=event.clientY-box.top;if(y>box.height*.78){setTools(!tools);return}if(mode==="single")save(Math.min(Math.max(0,index+(x<box.width/2?-1:1)),Math.max(0,urls.length-1)));}
  function changeMode(value:string){setMode(value);localStorage.setItem("hlibrary-reader-mode",value);if(value==="continuous")requestAnimationFrame(()=>requestAnimationFrame(()=>document.querySelector(`[data-page="${index}"]`)?.scrollIntoView()))}
  return <main className="reader" onClick={tap}>{resume&&progress.data?.hasProgress&&<button className="resume" onClick={e=>{e.stopPropagation();save(progress.data.pageIndex);if(mode==="continuous")requestAnimationFrame(()=>{const target=document.querySelector(`[data-page="${progress.data?.pageIndex}"]`) as HTMLElement|null;target?.scrollIntoView();const container=target?.closest(".reader") as HTMLElement|null;if(target&&container)container.scrollTop+=target.clientHeight*(progress.data?.pageOffset??0)/10000});setResume(false)}}>回到上次观看位置</button>}{tools&&<nav className="reader-tools" onClick={e=>e.stopPropagation()}><button onClick={()=>void exitReader()}>返回</button><span>{index+1}/{pages.data?.items.length??0} · 缓存 {urls.length}</span><button onClick={()=>changeMode(mode==="single"?"continuous":"single")}>{mode==="single"?"单页":"连续"}</button><button onClick={()=>setZoom(value=>Math.max(.5,value-.1))}>−</button><button onClick={()=>setZoom(value=>Math.min(4,value+.1))}>＋</button><button onClick={()=>setZoom(1)}>适配大小</button><button onClick={()=>{const value=prompt("跳转到第几页？");if(value)jump(Math.min(Math.max(0,Number(value)-1),(pages.data?.items.length??1)-1))}}>跳页</button></nav>}<div style={{transform:`scale(${zoom})`,transformOrigin:"top center"}} className={mode==="single"?"single-pages":"continuous-pages"}>{mode==="single"?(urls[index]?<img src={urls[index]}/>:<p>缓存中 {urls.length}/{pages.data?.items.length??0}</p>):urls.map((url,i)=><img key={url} src={url} onLoad={()=>{}} data-page={i}/>)}</div></main>;
}

type Filters = { kinds:string[];tagIds:number[];tagMode:string;ratingMode:string;rating:number };
function FilterPanel({token,value,change,close}:{token:string;value:Filters;change:(value:Filters)=>void;close:()=>void}){
  const [search,setSearch]=useState("");
  const [newTag,setNewTag]=useState("");const [newGroup,setNewGroup]=useState("");
  const [manageMode,setManageMode]=useState<null|"choose"|"groups"|"tags">(null);
  const tags=useQuery({queryKey:["filter-tags",search],queryFn:()=>api<Tag[]>(`/api/tags?search=${encodeURIComponent(search)}`,token)});
  const groups=useQuery({queryKey:["tag-groups"],queryFn:()=>api<{id:number;name:string;tags:number;comics:number;illustrations:number}[]>("/api/tag-groups",token)});
  async function addTag(){if(!newTag.trim())return;await api("/api/tags",token,{method:"POST",body:JSON.stringify({name:newTag,group_id:null})});setNewTag("");await tags.refetch()}
  async function addGroup(){if(!newGroup.trim())return;await api("/api/tag-groups",token,{method:"POST",body:JSON.stringify({name:newGroup})});setNewGroup("");await groups.refetch()}
  async function editTag(tag:Tag){const name=prompt("Tag 名称",tag.rawName??tag.name);if(!name)return;const target=prompt("目标分组 ID；留空表示未分组",tag.groupId?.toString()??"");await api(`/api/tags/${tag.id}`,token,{method:"PUT",body:JSON.stringify({name,group_id:target?Number(target):null})});await tags.refetch()}
  async function deleteTag(tag:Tag){if(!confirm(`“${tag.name}”用于 ${tag.works??0} 部作品。只删除 Tag 和关联，不删除作品文件。确认？`))return;await api(`/api/tags/${tag.id}`,token,{method:"DELETE"});change({...value,tagIds:value.tagIds.filter(id=>id!==tag.id)});await tags.refetch()}
  async function editGroup(group:{id:number;name:string}){const name=prompt("分组名称",group.name);if(!name)return;await api(`/api/tag-groups/${group.id}`,token,{method:"PUT",body:JSON.stringify({name})});await groups.refetch();await tags.refetch()}
  async function deleteGroup(group:{id:number;name:string;comics?:number;illustrations?:number}){const choice=prompt(`影响漫画 ${group.comics??0} 部、插画 ${group.illustrations??0} 部。输入 1：只删除分组并把 Tag 移到未分组；输入 2：删除分组及全部 Tag；留空取消`);if(choice!=="1"&&choice!=="2")return;if(choice==="2"&&!confirm("只会删除 Tag 和关联，不会删除作品文件。再次确认？"))return;await api(`/api/tag-groups/${group.id}?delete_tags=${choice==="2"}`,token,{method:"DELETE"});await groups.refetch();await tags.refetch()}
  const toggle=(values:string[]|number[],item:string|number)=>values.includes(item as never)?values.filter(value=>value!==item):[...values,item] as never[];
  return <div className="modal"><section className="panel filter">
    <header><h2>筛选</h2><button onClick={close}>关闭</button></header>
    <div className="tag-grid">{[["任意匹配","any"],["全部匹配","all"]].map(([label,mode])=><button key={mode} className={value.tagMode===mode?"selected":"quiet"} onClick={()=>change({...value,tagMode:mode})}>{label}</button>)}</div>
    <input placeholder="搜索 Tag 或分组" value={search} onChange={e=>setSearch(e.target.value)}/>
    <div className="tag-grid">
      {[["漫画","comic"],["插画","illustration"]].filter(([label])=>!search.trim()||label.includes(search.trim())).map(([label,kind])=><button key={kind} className={value.kinds[0]===kind?"selected":"quiet"} onClick={()=>change({...value,kinds:[kind]})}>{label}</button>)}
      {tags.data?.map(tag=><button key={tag.id} className={value.tagIds.includes(tag.id)?"selected":"quiet"} onClick={()=>change({...value,tagIds:toggle(value.tagIds,tag.id) as number[]})}>{tag.name}</button>)}
    </div>
    <h3>星级</h3><select value={`${value.ratingMode}:${value.rating}`} onChange={e=>{const [ratingMode,rating]=e.target.value.split(":");change({...value,ratingMode,rating:Number(rating)})}}><option value="any:0">全部</option><option value="unrated:0">未评价</option>{[1,2,3].map(r=><option key={`e${r}`} value={`exact:${r}`}>{r} 星</option>)}{[1,2,3].map(r=><option key={`a${r}`} value={`at_least:${r}`}>{r} 星及以上</option>)}</select>
    <button onClick={()=>setManageMode("choose")}>管理</button>
    <button className="quiet" onClick={()=>change({kinds:["comic"],tagIds:[],tagMode:"any",ratingMode:"any",rating:0})}>清除全部筛选</button>
    {manageMode==="choose"&&<div className="modal management-overlay" onClick={event=>{if(event.target===event.currentTarget)setManageMode(null)}}><section className="panel management-chooser"><button onClick={()=>setManageMode("groups")}>管理 Tag 分组</button><button onClick={()=>setManageMode("tags")}>管理 Tag</button></section></div>}
    {manageMode==="groups"&&<div className="modal management-overlay" onClick={event=>{if(event.target===event.currentTarget)setManageMode(null)}}><section className="panel"><header><h2>管理 Tag 分组</h2><button onClick={()=>setManageMode(null)}>关闭</button></header><input placeholder="新分组名称" value={newGroup} onChange={e=>setNewGroup(e.target.value)}/><button onClick={addGroup}>创建分组</button>{groups.data?.map(group=><div className="manage-row" key={`g${group.id}`}><span>{group.name} · {group.tags} 个 Tag</span><button onClick={()=>editGroup(group)}>改名</button><button className="quiet" onClick={()=>deleteGroup(group)}>删除</button></div>)}</section></div>}
    {manageMode==="tags"&&<div className="modal management-overlay" onClick={event=>{if(event.target===event.currentTarget)setManageMode(null)}}><section className="panel"><header><h2>管理 Tag</h2><button onClick={()=>setManageMode(null)}>关闭</button></header><div className="manage-row"><input placeholder="新 Tag 名称" value={newTag} onChange={e=>setNewTag(e.target.value)}/><button onClick={addTag}>创建新 Tag</button></div>{tags.data?.map(tag=><div className="manage-row" key={tag.id}><span>{tag.name} · {tag.works??0} 部</span><button onClick={()=>editTag(tag)}>改名/移动</button><button className="quiet" onClick={()=>deleteTag(tag)}>删除</button></div>)}</section></div>}
  </section></div>;
}

function NotificationPanel({token,close}:{token:string;close:()=>void}){
  const notices=useQuery({queryKey:["notifications"],queryFn:()=>api<{items:{id:number;title:string;details:string;createdAt:string}[];unread:number}>("/api/notifications",token)});
  const replacements=useQuery({queryKey:["replacements"],queryFn:()=>api<{workId:number;fileName:string}[]>("/api/replacements",token)});
  useEffect(()=>{void api("/api/notifications/read",token,{method:"POST"})},[token]);
  async function remove(id:number){await api(`/api/notifications/${id}`,token,{method:"DELETE"});await notices.refetch()}
  async function resolve(workId:number,preserve:boolean){await api(`/api/replacements/${workId}?preserve_metadata=${preserve}`,token,{method:"POST"});await replacements.refetch();await notices.refetch()}
  async function clear(){if(!confirm("清空全部通知？"))return;await api("/api/notifications/all",token,{method:"DELETE"});await notices.refetch()}
  return <div className="modal"><section className="panel filter"><header><h2>通知</h2><button onClick={close}>关闭</button></header>{replacements.data?.map(item=><div className="upload-item" key={`r${item.workId}`}><strong>{item.fileName} 的内容已被替换</strong><p>选择如何处理后才能再次打开作品。</p><button onClick={()=>resolve(item.workId,true)}>保留原资料</button><button className="quiet" onClick={()=>resolve(item.workId,false)}>当作新作品</button></div>)}{notices.data?.items.map(item=><div className="upload-item" key={item.id}><strong>{item.title}</strong><small>{new Date(item.createdAt).toLocaleString()}</small><p>{(()=>{try{const value=JSON.parse(item.details);return Array.isArray(value)?value.join("、"):String(value)}catch{return item.details}})()}</p><button className="quiet" onClick={()=>remove(item.id)}>删除</button></div>)}{notices.data?.items.length===0&&replacements.data?.length===0&&<p>暂无通知</p>}<button className="quiet" onClick={clear}>清空全部通知</button></section></div>;
}

function SettingsPanel({token,close,disconnect}:{token:string;close:()=>void;disconnect:()=>void}){
  const [theme,setTheme]=useState(()=>localStorage.getItem("hlibrary-theme")??"system");
  const [computerUrl,setComputerUrl]=useState("");
  const device=useQuery({queryKey:["current-device"],queryFn:()=>api<{name:string}>("/api/devices/me",token)});const computer=useQuery({queryKey:["computer"],queryFn:()=>api<{computerName:string}>("/api/library/status",token)});
  function change(value:string){setTheme(value);localStorage.setItem("hlibrary-theme",value);document.documentElement.dataset.theme=value}
  return <div className="modal"><section className="panel"><header><h2>设置</h2><button onClick={close}>关闭</button></header><p>当前电脑：{computer.data?.computerName??"正在读取"}</p><p>当前设备：{device.data?.name??"正在读取"}</p><label>外观主题<select value={theme} onChange={e=>change(e.target.value)}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label><label>切换到其他已配对电脑<input placeholder="例如 http://192.168.1.20:18459" value={computerUrl} onChange={e=>setComputerUrl(e.target.value)}/></label><button onClick={()=>{if(computerUrl)location.href=rememberComputer(computerUrl)}}>保存并打开电脑入口</button>{savedComputers().map(url=><button className="quiet" key={url} onClick={()=>location.href=url}>{url}{url===location.origin?"（当前）":""}</button>)}<button className="quiet" onClick={disconnect}>断开当前电脑</button></section></div>;
}

function Library({ token, disconnect }: { token: string; disconnect: () => void }) {
  const [input, setInput] = useState(""); const [search, setSearch] = useState(""); const [page, setPage] = useState(1);
  const [selected,setSelected]=useState<number|null>(null); const [reading,setReading]=useState(false);
  const [showFilters,setShowFilters]=useState(false);const [filters,setFilters]=useState<Filters>({kinds:["comic"],tagIds:[],tagMode:"any",ratingMode:"any",rating:0});
  const [showNotifications,setShowNotifications]=useState(false);
  const [showSettings,setShowSettings]=useState(false);
  const [sort,setSort]=useState(()=>localStorage.getItem("hlibrary-sort")??"added");const [descending,setDescending]=useState(()=>localStorage.getItem("hlibrary-sort-direction")!=="asc");
  const [unread,setUnread]=useState(0);
  useEffect(()=>{const controller=new AbortController();void (async()=>{try{const response=await fetch("/api/events",{headers:{Authorization:`Bearer ${token}`},signal:controller.signal});const reader=response.body?.getReader();const decoder=new TextDecoder();let buffer="";while(reader){const value=await reader.read();if(value.done)break;buffer+=decoder.decode(value.value,{stream:true});const events=buffer.split("\n\n");buffer=events.pop()??"";for(const event of events){const line=event.split("\n").find(value=>value.startsWith("data: "));if(line)setUnread(JSON.parse(line.slice(6)).unread)}}}catch{/* connection status is shown by normal queries */}})();return()=>controller.abort()},[token]);
  useEffect(() => { const timer = setTimeout(() => { setSearch(input); setPage(1); }, 400); return () => clearTimeout(timer); }, [input]);
  const filterQuery=`&kinds=${filters.kinds.join(",")}&tag_ids=${filters.tagIds.join(",")}&tag_mode=${filters.tagMode}&rating_mode=${filters.ratingMode}&rating=${filters.rating}`;
  const works = useQuery({ queryKey: ["works", search, page,filters,sort,descending], queryFn: () => api<WorkPage>(`/api/works?text=${encodeURIComponent(search)}&page=${page}&sort=${sort}&descending=${descending}${filterQuery}`, token) });
  if (works.error && String(works.error).includes("配对")) disconnect();
  if(selected!==null&&reading)return <MobileReader id={selected} token={token} back={()=>setReading(false)}/>;
  if(selected!==null)return <DetailView id={selected} token={token} back={()=>setSelected(null)} read={()=>setReading(true)}/>;
  return <main className="library"><header><h1>H库</h1><div><button className="quiet" onClick={()=>{setShowNotifications(true);setUnread(0)}}>通知{unread?` ${unread}`:""}</button> <button className="quiet" onClick={()=>setShowSettings(true)}>设置</button></div></header>
    <div className="toolbar"><input placeholder="搜索编号或标题" value={input} onChange={e => setInput(e.target.value)} /><button onClick={()=>setShowFilters(true)}>筛选</button><select value={sort} onChange={e=>{setSort(e.target.value);localStorage.setItem("hlibrary-sort",e.target.value);setPage(1)}}><option value="added">添加时间</option><option value="file_name">文件名/编号</option><option value="title">标题</option><option value="rating">星级</option></select><button onClick={()=>{setDescending(value=>{localStorage.setItem("hlibrary-sort-direction",!value?"desc":"asc");return !value})}}>{descending?"↓":"↑"}</button></div>
    {works.isPending && <p>正在载入…</p>}{works.isError && <p className="error">{works.error.message}</p>}
    <section className="works">{works.data?.items.map(work => <article className="work" key={work.id} onClick={()=>setSelected(work.id)}>
      <div className="cover"><AuthImage path={`/api/works/${work.id}/thumbnail`} token={token} /></div>
      <div className="meta"><h2>{work.title}</h2><p>{work.kind === "comic" ? work.number : work.fileName}</p>
        <div className="tags"><span className="system-tag">{work.kind==="comic"?"漫画":"插画"}</span>{work.tags.slice(0,3).map(tag => <span className={tag.groupId==null?"ungrouped":""} key={tag.id}>{tag.name}</span>)}{work.tags.length>3&&<span className="more-tags">+{work.tags.length-3}</span>}</div><p className="stars">{"★".repeat(work.rating)}{"☆".repeat(3-work.rating)}</p></div>
    </article>)}</section>
    {works.data && <nav className="pages"><button disabled={page===1} onClick={()=>setPage(1)}>首页</button><button disabled={page===1} onClick={()=>setPage(page-1)}>上页</button><input aria-label="跳转页码" type="number" min="1" max={works.data.pages} value={page} onChange={e=>setPage(Math.min(works.data?.pages??1,Math.max(1,Number(e.target.value))))}/><span>/{works.data.pages} · {works.data.total} 部</span><button disabled={page===works.data.pages} onClick={()=>setPage(page+1)}>下页</button><button disabled={page===works.data.pages} onClick={()=>setPage(works.data.pages)}>末页</button></nav>}
    {showFilters&&<FilterPanel token={token} value={filters} change={value=>{setFilters(value);setPage(1)}} close={()=>setShowFilters(false)}/>}
    {showNotifications&&<NotificationPanel token={token} close={()=>setShowNotifications(false)}/>}
    {showSettings&&<SettingsPanel token={token} close={()=>setShowSettings(false)} disconnect={disconnect}/>} 
  </main>;
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(tokenKey) ?? "");
  useEffect(()=>{document.documentElement.dataset.theme=localStorage.getItem("hlibrary-theme")??"system"},[]);
  const disconnect = () => { if(token)void fetch("/api/devices/me",{method:"DELETE",headers:{Authorization:`Bearer ${token}`}});localStorage.removeItem(tokenKey);setToken(""); };
  return token ? <Library token={token} disconnect={disconnect} /> : <Pair onPaired={setToken} />;
}
