import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { setMessages, t, tf } from "./i18n";

type WorkTag = { id:number;name:string;groupId?:number|null;groupName?:string|null };
type Work = { id:number;kind:"comic"|"illustration";fileName:string;number:string|null;title:string;rating:number;coverVersion:string;tags:WorkTag[] };
type WorkPage = { items:Work[];total:number;page:number;pages:number };
type Detail = Work & { fingerprint:string;previews:string[];coverMember:string|null };
type Tag = WorkTag & { rawName?:string;works?:number };
type Group = { id:number;name:string;tags:number;comics:number;illustrations:number;system?:boolean };
type Filters = { kinds:string[];tagIds:number[];tagMode:string;ratingMode:string;rating:number };
type Language = { code:string;name:string };
type LibraryViewState = { input:string;search:string;page:number;selected:Work|null;reading:boolean;showFilters:boolean;filters:Filters;showNotifications:boolean;showSettings:boolean;scrollY:number };
const defaultFilters = ():Filters => ({kinds:["comic"],tagIds:[],tagMode:"any",ratingMode:"any",rating:0});
const libraryViewKey = `hmanga-library-view:${location.host}`;
function loadLibraryView():LibraryViewState{const fallback={input:"",search:"",page:1,selected:null,reading:false,showFilters:false,filters:defaultFilters(),showNotifications:false,showSettings:false,scrollY:0};try{return{...fallback,...JSON.parse(sessionStorage.getItem(libraryViewKey)??"{}")}}catch{return fallback}}

const tokenKey = `hmanga-token:${location.host}`;
const authorGroupName = "\u4f5c\u8005";
const categoryGroupName = "\u7c7b\u522b";
const isAuthor = (tag:WorkTag) => tag.groupName === authorGroupName;
const tagClass = (tag:WorkTag) => isAuthor(tag) ? "author-tag" : tag.groupId == null ? "ungrouped" : "";

async function api<T>(path:string,token:string,init?:RequestInit):Promise<T>{const response=await fetch(path,{cache:"no-store",...init,headers:{"Content-Type":"application/json",Authorization:`Bearer ${token}`,...init?.headers}});if(!response.ok)throw new Error((await response.json().catch(()=>null))?.detail??t("error.request_failed"));return response.json() as Promise<T>}

function Icon({name}:{name:"bell"|"settings"|"back"|"filter"}){
  const paths={bell:"M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4",settings:"M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.86 2.86-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1.05 1.57V21h-4v-.03A1.7 1.7 0 0 0 8.9 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.86-2.86.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.57-1.05H3v-4h.03A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.88l-.06-.06L7.06 4.1l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.57V3h4v.03A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.86 2.86-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.57 1.05H21v4h-.03A1.7 1.7 0 0 0 19.4 15",back:"M15 18l-6-6 6-6",filter:"M4 6h16M7 12h10M10 18h4"};
  return <svg viewBox="0 0 24 24" aria-hidden="true">
<path d={paths[name]}/>
</svg>
}

function Modal({children,close,wide=false,warning=false,className=""}:{children:React.ReactNode;close?:()=>void;wide?:boolean;warning?:boolean;className?:string}){
  return <div className="modal" onPointerDown={event=>event.stopPropagation()} onPointerUp={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();if(event.target===event.currentTarget)close?.()}}>
<section className={`panel floating-card ${wide?"wide":""} ${warning?"warning-card":""} ${className}`}>{children}</section>
</div>
}

function Pair({onPaired}:{onPaired:(token:string)=>void}){
  const[code,setCode]=useState(()=>new URLSearchParams(location.search).get("code")?.replace(/\D/g,"").slice(0,6)??"");const[name,setName]=useState(t("label.my_phone"));const[error,setError]=useState("");
  async function submit(event:FormEvent){event.preventDefault();setError("");try{const result=await api<{token:string}>("/api/pair","",{method:"POST",body:JSON.stringify({code,name}),headers:{Authorization:""}});localStorage.setItem(tokenKey,result.token);onPaired(result.token);history.replaceState(null,"",location.pathname)}catch(reason){setError(reason instanceof Error?reason.message:t("error.pairing_failed"))}}
  return <main className="pair-page">
<form className="panel pair-card" onSubmit={submit}>
<div className="brand-mark">H</div>
<p className="eyebrow">{t("label.connect_computer")}</p>
<h1>{t("label.connect_app")}</h1>
<p className="muted">{t("message.pairing_code_hint")}</p>
<label>{t("label.device_name")}<input value={name} onChange={e=>setName(e.target.value)}/>
</label>
<label>{t("label.pairing_code")}<input className="pair-code" inputMode="numeric" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,""))}/>
</label>{error&&<p className="error-box">{error}</p>}<button className="primary full" disabled={code.length!==6}>{t("status.pairing_complete")}</button>
</form>
</main>
}

function AuthImage({path,token}:{path:string;token:string}){const[url,setUrl]=useState("");useEffect(()=>{let current="";fetch(path,{headers:{Authorization:`Bearer ${token}`}}).then(response=>response.ok?response.blob():Promise.reject()).then(blob=>{current=URL.createObjectURL(blob);setUrl(current)}).catch(()=>setUrl(""));return()=>{if(current)URL.revokeObjectURL(current)}},[path,token]);return url?<img src={url} alt={t("label.cover")}/>:<div className="cover-placeholder" aria-hidden="true"/>}

function LoadedPreview({path,token,release}:{path:string;token:string;release:()=>void}){const[url,setUrl]=useState("");useEffect(()=>{const controller=new AbortController();let current="";fetch(path,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal}).then(response=>response.ok?response.blob():Promise.reject()).then(blob=>{current=URL.createObjectURL(blob);setUrl(current)}).catch(()=>{});return()=>{controller.abort();if(current)URL.revokeObjectURL(current)}},[path,token]);if(!url)return null;return <div className="preview-large" onContextMenu={event=>event.preventDefault()} onPointerUp={release} onPointerCancel={release}>
<img src={url} alt={t("label.preview_large")} draggable={false}/>
</div>}

function CoverSelector({id,token,current,choose,close}:{id:number;token:string;current:string|null;choose:(member:string)=>void;close:()=>void}){
  const pages=useQuery({queryKey:["cover-pages",id],queryFn:()=>api<{items:string[]}>(`/api/works/${id}/pages`,token)});const[index,setIndex]=useState(0);useEffect(()=>{const found=pages.data?.items.indexOf(current??"")??-1;if(found>=0)setIndex(found)},[pages.data,current]);const count=pages.data?.items.length??0;
  return <Modal close={close} className="cover-selector-card">
<CardHeader title={t("action.select_cover")} close={close}/>{count>0&&<div className="cover-picker">
<AuthImage path={`/api/works/${id}/pages/${index}`} token={token}/>
</div>}<p className="cover-page-number center-text muted">{count?tf("cover.page_summary",{page:index+1,pages:count}):t("label.no_available_images")}</p>
<div className="split-actions">
<button disabled={index===0} onClick={()=>setIndex(Math.max(0,index-1))}>{t("label.previous_image")}</button>
<button disabled={index>=count-1} onClick={()=>setIndex(Math.min(count-1,index+1))}>{t("label.next_image")}</button>
</div>
<button className="primary full" disabled={!count} onClick={()=>{const member=pages.data?.items[index];if(member)choose(member)}}>{t("label.set_as_cover")}</button>
</Modal>
}

function CardHeader({title,close}:{title:string;close:()=>void}){return <header className="card-header">
<h2>{title}</h2>
<button className="icon-button" aria-label={t("action.close")} onClick={close}>×</button>
</header>}

function PreviewStrip({id,token,members}:{id:number;token:string;members:string[]}){const[large,setLarge]=useState<number|null>(null);const timer=useRef<number|undefined>(undefined);const start=useRef({x:0,y:0});function down(index:number,event:React.PointerEvent){event.currentTarget.setPointerCapture(event.pointerId);start.current={x:event.clientX,y:event.clientY};timer.current=window.setTimeout(()=>setLarge(index),100)}function move(event:React.PointerEvent){if(Math.hypot(event.clientX-start.current.x,event.clientY-start.current.y)>10)clearTimeout(timer.current)}function up(){clearTimeout(timer.current);setLarge(null)}function blockNativeMenu(event:React.SyntheticEvent){event.preventDefault()}return <>
<div className="preview-strip">{members.map((member,index)=>
<div className="preview-touch-target" key={member} onContextMenu={blockNativeMenu} onDragStart={blockNativeMenu} onPointerDown={event=>down(index,event)} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
<AuthImage path={`/api/works/${id}/previews/${index}`} token={token}/>
</div>)}</div>{large!==null&&<LoadedPreview path={`/api/works/${id}/previews/${large}`} token={token} release={up}/>}</>}

function DetailView({id,token,back,read,filter}:{id:number;token:string;back:()=>void;read:()=>void;filter:(kind:Work["kind"],tagId:number|null)=>void}){
  const detail=useQuery({queryKey:["detail",id],queryFn:()=>api<Detail>(`/api/works/${id}`,token)});const tags=useQuery({queryKey:["tags"],queryFn:()=>api<Tag[]>("/api/tags",token)});const[editing,setEditing]=useState(false);const[title,setTitle]=useState("");const[rating,setRating]=useState(0);const[selectedTags,setSelectedTags]=useState<number[]>([]);const[tagSearch,setTagSearch]=useState("");const[cover,setCover]=useState<string|null>(null);const[coverOpen,setCoverOpen]=useState(false);const[managingTags,setManagingTags]=useState(false);const[discard,setDiscard]=useState(false);const[deleteWork,setDeleteWork]=useState(false);
  useEffect(()=>{if(detail.data){setTitle(detail.data.title);setRating(detail.data.rating);setSelectedTags(detail.data.tags.map(tag=>tag.id));setCover(detail.data.coverMember)}},[detail.data]);if(!detail.data)return <main className="detail-page">
<div className="loading">{t("status.loading_details")}</div>
</main>;const work=detail.data;const dirty=title!==work.title||rating!==work.rating||cover!==work.coverMember||selectedTags.join(",")!==work.tags.map(tag=>tag.id).join(",");
  function cancelEdit(){setTitle(work.title);setRating(work.rating);setSelectedTags(work.tags.map(tag=>tag.id));setCover(work.coverMember);setEditing(false);setDiscard(false)}async function save(){await api(`/api/works/${id}`,token,{method:"PUT",body:JSON.stringify({title,rating,tag_ids:selectedTags,cover_member:cover})});setEditing(false);await detail.refetch()}
  return <main className="detail-page">
<section className="detail-card">
<div className="detail-top">
<button className="icon-button" onClick={()=>editing&&dirty?setDiscard(true):back()}>
<Icon name="back"/>
</button>
<span>{editing?t("action.edit_work"):t("label.work_detail")}</span>
<span/>
</div>{!editing&&<div className="detail-cover">
<AuthImage path={`/api/works/${id}/thumbnail?v=${encodeURIComponent(work.coverVersion)}`} token={token}/>
</div>}<div className="detail-body">{editing?<>
<label>{t("label.title")}<input value={title} onChange={e=>setTitle(e.target.value)}/>
</label>
<label>{t("label.rating_zero_to_three")}<div className="rating-picker">{[0,1,2,3].map(value=>
<button key={value} className={rating===value?"selected":""} onClick={()=>setRating(value)}>{value===0?t("label.unrated"):"★".repeat(value)}</button>)}</div>
</label>
<input className="edit-tag-search" placeholder={t("label.search_tags_or_groups")} value={tagSearch} onChange={e=>setTagSearch(e.target.value)}/>
<div className="tag-grid edit-tags">{tags.data?.filter(tag=>tag.name.toLocaleLowerCase().includes(tagSearch.trim().toLocaleLowerCase())).sort((a,b)=>Number(!isAuthor(a))-Number(!isAuthor(b))||b.name.length-a.name.length).map(tag=>
<button className={`${selectedTags.includes(tag.id)?"selected":""} ${tagClass(tag)}`} key={tag.id} onClick={()=>setSelectedTags(values=>values.includes(tag.id)?values.filter(value=>value!==tag.id):[...values,tag.id])}>{tag.name}</button>)}</div>
<button className="full" onClick={()=>setManagingTags(true)}>{t("label.manage_tags")}</button>{work.kind==="comic"&&<button className="full" onClick={()=>setCoverOpen(true)}>{t("label.change_cover")}</button>}<button className="primary full" onClick={()=>void save()}>{t("action.save")}</button>
</>:<>
<h1>{work.title}</h1>
<p className="work-number">{work.kind==="comic"?work.number||"":work.fileName}</p>
<p className="stars">{"★".repeat(work.rating)}{"☆".repeat(3-work.rating)}</p>
<div className="tags detail-tags">
<button className="system-tag" onClick={()=>filter(work.kind,null)}>{work.kind==="comic"?t("label.comic"):t("label.illustration")}</button>{work.tags.map(tag=>
<button className={tagClass(tag)} key={tag.id} onClick={()=>filter(work.kind,tag.id)}>{tag.name}</button>)}</div>{work.kind==="comic"&&<>
<PreviewStrip id={id} token={token} members={work.previews}/>
<button className="primary full" onClick={read}>{t("label.start_reading")}</button>
</>}<button className="full" onClick={()=>setEditing(true)}>{t("action.edit")}</button>
<button className="danger-outline full" onClick={()=>setDeleteWork(true)}>{t("action.delete_work")}</button>
</>}</div>
</section>{coverOpen&&<CoverSelector id={id} token={token} current={cover} close={()=>setCoverOpen(false)} choose={member=>{setCover(member);setCoverOpen(false)}}/>}{managingTags&&<TagManagement token={token} close={()=>setManagingTags(false)} changed={createdId=>{if(createdId)setSelectedTags(values=>values.includes(createdId)?values:[...values,createdId]);void tags.refetch()}}/>}{deleteWork&&<Modal close={()=>setDeleteWork(false)} warning>
<h2>{t("confirm.delete_work_title")}</h2>
<p>{tf("work.delete_confirm",{file_name:work.fileName})}</p>
<div className="split-actions">
<button onClick={()=>setDeleteWork(false)}>{t("action.cancel")}</button>
<button className="danger" onClick={()=>void api(`/api/works/${id}`,token,{method:"DELETE"}).then(()=>{setDeleteWork(false);back()})}>{t("confirm.confirm_delete")}</button>
</div>
</Modal>}{discard&&<Modal close={()=>setDiscard(false)} warning>
<h2>{t("confirm.discard_changes_title")}</h2>
<p>{t("message.unsaved_work_changes")}</p>
<div className="split-actions">
<button onClick={()=>setDiscard(false)}>{t("label.continue_editing")}</button>
<button className="danger" onClick={()=>{cancelEdit();back()}}>{t("label.discard_and_return")}</button>
</div>
</Modal>}</main>
}

function MobileReader({id,title,token,back}:{id:number;title:string;token:string;back:()=>void}){
  const readerViewKey=`hmanga-reader-view:${location.host}:${id}`;const restoredPosition=useRef((()=>{try{return JSON.parse(sessionStorage.getItem(readerViewKey)??"") as {index:number;offset:number}}catch{return{index:0,offset:0}}})()).current;const restoredPositionApplied=useRef(false);
  const pages=useQuery({queryKey:["pages",id],queryFn:()=>api<{items:string[];fingerprint:string}>(`/api/works/${id}/pages`,token)});const progress=useQuery({queryKey:["progress",id],queryFn:()=>api<{pageIndex:number;pageOffset:number;hasProgress:boolean;fingerprint:string}>(`/api/works/${id}/progress`,token)});const[urls,setUrls]=useState<string[]>([]);const[index,setIndex]=useState(Math.max(0,restoredPosition.index));const[mode,setMode]=useState(()=>localStorage.getItem("hmanga-reader-mode")??"continuous");const[tools,setTools]=useState(true);const[resume,setResume]=useState(true);const[zoom,setZoom]=useState(1);const[jumpValue,setJumpValue]=useState(String(Math.max(0,restoredPosition.index)+1));const[readerError,setReaderError]=useState("");const currentPosition=useRef(restoredPosition);
  useEffect(()=>{if(!pages.data)return;let cancelled=false;const made:string[]=[];const cacheName=`hmanga-session-${id}-${pages.data.fingerprint}`;async function download(retried=false){try{const cache="caches"in window?await caches.open(cacheName):null;for(let i=0;i<(pages.data?.items.length??0)&&!cancelled;i++){const path=`/api/works/${id}/pages/${i}`;const response=await fetch(path,{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw new Error();if(cache)await cache.put(new Request(path),response.clone());const url=URL.createObjectURL(await response.blob());made.push(url);if(!cancelled)setUrls([...made])}}catch{made.splice(0).forEach(URL.revokeObjectURL);setUrls([]);if("caches"in window)await caches.delete(cacheName);if(!retried&&!cancelled)await download(true);else setReaderError(t("error.offline_cache_full"))}}void download();return()=>{cancelled=true;made.forEach(URL.revokeObjectURL);if("caches"in window)void caches.delete(cacheName)}},[pages.data,id,token]);useEffect(()=>{const timer=setTimeout(()=>setResume(false),5000);return()=>clearTimeout(timer)},[]);useEffect(()=>{if(!tools)return;const timer=setTimeout(()=>setTools(false),5000);return()=>clearTimeout(timer)},[tools,index,mode]);useEffect(()=>{const key=`hmanga-pending-progress:${location.host}:${id}`;async function sync(){const pending=localStorage.getItem(key);if(!pending)return;try{await api(`/api/works/${id}/progress`,token,{method:"PUT",body:pending});localStorage.removeItem(key)}catch{/* retry when this computer is reachable */}}window.addEventListener("online",sync);void sync();return()=>window.removeEventListener("online",sync)},[id,token]);useEffect(()=>{if(mode!=="continuous")return;const observer=new IntersectionObserver(entries=>{const visible=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(!visible)return;const target=visible.target as HTMLElement;const next=Number(target.dataset.page);const rect=target.getBoundingClientRect();currentPosition.current={index:next,offset:Math.min(10000,Math.max(0,Math.round(-rect.top/Math.max(1,rect.height)*10000)))};persistPosition();setIndex(next);setJumpValue(String(next+1))},{threshold:[.25,.5,.75]});document.querySelectorAll(".continuous-pages img").forEach(image=>observer.observe(image));return()=>observer.disconnect()},[mode,urls]);useEffect(()=>{if(mode!=="continuous"||restoredPositionApplied.current||urls.length<=restoredPosition.index)return;const image=document.querySelector(`[data-page="${restoredPosition.index}"]`) as HTMLImageElement|null;const reader=document.querySelector(".reader") as HTMLElement|null;if(!image||!reader)return;const restore=()=>{reader.scrollTop=image.offsetTop+image.height*Math.min(10000,Math.max(0,restoredPosition.offset))/10000;restoredPositionApplied.current=true};if(image.complete)requestAnimationFrame(restore);else image.addEventListener("load",restore,{once:true})},[mode,urls,restoredPosition]);
  function persistPosition(){sessionStorage.setItem(readerViewKey,JSON.stringify(currentPosition.current))}function setPage(next:number){const safe=Math.min(Math.max(0,next),Math.max(0,urls.length-1));currentPosition.current={index:safe,offset:0};persistPosition();setIndex(safe);setJumpValue(String(safe+1))}function jump(next:number){setPage(next);if(mode==="continuous")requestAnimationFrame(()=>document.querySelector(`[data-page="${next}"]`)?.scrollIntoView())}async function exitReader(){sessionStorage.removeItem(readerViewKey);if(pages.data){const position=currentPosition.current;const body=JSON.stringify({page_index:position.index,page_offset:position.offset,fingerprint:pages.data.fingerprint});const key=`hmanga-pending-progress:${location.host}:${id}`;localStorage.setItem(key,body);try{await api(`/api/works/${id}/progress`,token,{method:"PUT",body});localStorage.removeItem(key)}catch{/* next connection retries elsewhere */}}back()}function tap(event:React.MouseEvent){if(mode==="continuous"){setTools(value=>!value);return}if(tools){setTools(false);return}const box=event.currentTarget.getBoundingClientRect();const y=event.clientY-box.top;setPage(index+(y<box.height/2?-1:1))}function changeMode(){const value=mode==="single"?"continuous":"single";setMode(value);localStorage.setItem("hmanga-reader-mode",value);if(value==="continuous")requestAnimationFrame(()=>requestAnimationFrame(()=>document.querySelector(`[data-page="${index}"]`)?.scrollIntoView()))}
  return <main className="reader" onClick={tap}>{resume&&progress.data?.hasProgress&&<button className="resume" onClick={event=>{event.stopPropagation();jump(progress.data.pageIndex);setResume(false)}}>{t("label.resume_last_position")}</button>}{tools&&<>
<header className="reader-title" onClick={e=>e.stopPropagation()}>
<button onClick={()=>void exitReader()}>
<Icon name="back"/>
</button>
<strong>{title}</strong>
<span/>
</header>
<nav className="reader-tools" onClick={e=>e.stopPropagation()}>
<span>{index+1}/{pages.data?.items.length??0}</span>
<button onClick={changeMode}>{mode==="single"?t("label.single_page"):t("label.vertical_continuous")}</button>
<button onClick={()=>setZoom(value=>Math.max(.5,value-.1))}>−</button>
<button onClick={()=>setZoom(value=>Math.min(4,value+.1))}>＋</button>
<button onClick={()=>setZoom(1)}>{t("label.fit_to_size")}</button>
<form onSubmit={event=>{event.preventDefault();jump(Number(jumpValue)-1)}}>
<input aria-label={t("action.jump_to_page")} inputMode="numeric" value={jumpValue} onChange={e=>setJumpValue(e.target.value)}/>
</form>
</nav>
</>}{!tools&&<button className="reader-reveal" aria-label={t("label.show_reader_toolbar")} onClick={event=>{event.stopPropagation();setTools(true)}}>⌃</button>}{readerError&&<div className="reader-notice" onClick={e=>e.stopPropagation()}>{readerError}<button onClick={()=>setReaderError("")}>{t("label.understood")}</button>
</div>}<div style={zoom===1?undefined:{transform:`scale(${zoom})`,transformOrigin:"top center"}} className={mode==="single"?"single-pages":"continuous-pages"}>{mode==="single"?(urls[index]?<img src={urls[index]}/>:<p>{tf("reader.caching",{loaded:urls.length,total:pages.data?.items.length??0})}</p>):urls.map((url,i)=>
<img key={url} src={url} data-page={i}/>)}</div>
</main>
}

function FilterPanel({token,value,change,close}:{token:string;value:Filters;change:(value:Filters)=>void;close:()=>void}){
  const[search,setSearch]=useState("");const[managing,setManaging]=useState(false);const tags=useQuery({queryKey:["filter-tags",search],queryFn:()=>api<Tag[]>(`/api/tags?search=${encodeURIComponent(search)}`,token)});const toggle=(values:number[],item:number)=>values.includes(item)?values.filter(value=>value!==item):[...values,item];
  const revealAuthors=search.trim().includes(t("label.author"));const visibleTags=tags.data?.filter(tag=>!isAuthor(tag)||revealAuthors||value.tagIds.includes(tag.id));
  return <Modal close={close} wide>
<CardHeader title={t("label.filter")} close={close}/>
<div className="segment">
<button className={value.tagMode==="any"?"selected":""} onClick={()=>change({...value,tagMode:"any"})}>{t("label.match_any")}</button>
<button className={value.tagMode==="all"?"selected":""} onClick={()=>change({...value,tagMode:"all"})}>{t("label.match_all")}</button>
</div>
<input placeholder={t("label.search_tags_or_groups")} value={search} onChange={e=>setSearch(e.target.value)}/>
<div className="tag-grid filter-tags">
<button className={value.kinds[0]==="comic"?"selected system-tag":"system-tag"} onClick={()=>change({...value,kinds:["comic"]})}>{t("label.comic")}</button>
<button className={value.kinds[0]==="illustration"?"selected system-tag":"system-tag"} onClick={()=>change({...value,kinds:["illustration"]})}>{t("label.illustration")}</button>{visibleTags?.map(tag=>
<button className={`${value.tagIds.includes(tag.id)?"selected":""} ${tagClass(tag)}`} key={tag.id} onClick={()=>change({...value,tagIds:toggle(value.tagIds,tag.id)})}>{tag.name}</button>)}</div>
<label>{t("label.rating_filter")}<select value={`${value.ratingMode}:${value.rating}`} onChange={e=>{const[ratingMode,rating]=e.target.value.split(":");change({...value,ratingMode,rating:Number(rating)})}}>
<option value="any:0">{t("label.all_ratings")}</option>
<option value="unrated:0">{t("label.unrated")}</option>{[1,2,3].map(r=>
<option key={`e${r}`} value={`exact:${r}`}>{tf("rating.exact",{rating:r})}</option>)}{[1,2,3].map(r=>
<option key={`a${r}`} value={`at_least:${r}`}>{tf("rating.at_least",{rating:r})}</option>)}</select>
</label>
<div className="split-actions">
<button onClick={()=>change({kinds:["comic"],tagIds:[],tagMode:"any",ratingMode:"any",rating:0})}>{t("action.clear_all_filters")}</button>
<button onClick={()=>setManaging(true)}>{t("label.manage_tags")}</button>
</div>{managing&&<TagManagement token={token} close={()=>setManaging(false)} changed={()=>void tags.refetch()}/>}</Modal>
}

function TagManagement({token,close,changed}:{token:string;close:()=>void;changed:(createdId?:number)=>void}){
  const[newName,setNewName]=useState("");const[newGroupId,setNewGroupId]=useState<number|null>(null);const[editing,setEditing]=useState<Tag|null>(null);const[deleteTag,setDeleteTag]=useState<Tag|null>(null);const tags=useQuery({queryKey:["manage-tags"],queryFn:()=>api<Tag[]>("/api/tags",token)});const groups=useQuery({queryKey:["manage-groups"],queryFn:()=>api<Group[]>("/api/tag-groups",token)});const categoryId=groups.data?.find(group=>group.name===categoryGroupName)?.id??null;const createGroupId=newGroupId??categoryId;const creatingAuthor=groups.data?.find(group=>group.id===createGroupId)?.name===authorGroupName;
  async function refresh(){await Promise.all([tags.refetch(),groups.refetch()]);changed()}async function create(){if(!newName.trim()||createGroupId===null)return;const created=await api<{id:number}>("/api/tags",token,{method:"POST",body:JSON.stringify({name:newName,group_id:createGroupId})});setNewName("");await Promise.all([tags.refetch(),groups.refetch()]);changed(created.id)}
  return <Modal close={close} wide>
<CardHeader title={t("label.manage_tags")} close={close}/>
<div className="create-row">
<input maxLength={creatingAuthor?200:5} placeholder={t("label.new_tag_name")} value={newName} onChange={e=>setNewName(e.target.value)}/>
<select aria-label={t("label.new_tag_group")} value={createGroupId??""} onChange={e=>setNewGroupId(Number(e.target.value))}>{groups.data?.map(group=>
<option value={group.id} key={group.id}>{group.name}</option>)}</select>
<button onClick={()=>void create()}>{t("action.create")}</button>
</div>
<div className="management-list">{tags.data?.map(tag=>
<div className="manage-row" key={tag.id}>
<span className={`tag-pill ${tagClass(tag)}`}>{tag.name}</span>
<small>{tf("works.count",{count:tag.works??0})}</small>
<button onClick={()=>setEditing(tag)}>{t("action.edit")}</button>
<button className="danger-outline" onClick={()=>setDeleteTag(tag)}>{t("action.delete")}</button>
</div>)}</div>{editing&&<Modal close={()=>setEditing(null)}>
<EditTag tag={editing} groups={groups.data??[]} token={token} done={()=>{setEditing(null);void refresh()}}/>
</Modal>}{deleteTag&&<Modal close={()=>setDeleteTag(null)} warning>
<h2>{t("confirm.delete_tag_title")}</h2>
<p>{tf("tag.delete_confirm",{name:deleteTag.name,count:deleteTag.works??0})}</p>
<div className="split-actions">
<button onClick={()=>setDeleteTag(null)}>{t("action.cancel")}</button>
<button className="danger" onClick={()=>void api(`/api/tags/${deleteTag.id}`,token,{method:"DELETE"}).then(()=>{setDeleteTag(null);return refresh()})}>{t("confirm.confirm_delete")}</button>
</div>
</Modal>}</Modal>
}

function EditTag({tag,groups,token,done}:{tag:Tag;groups:Group[];token:string;done:()=>void}){const[name,setName]=useState(tag.rawName??tag.name);const[groupId,setGroupId]=useState<number>(tag.groupId??groups.find(group=>group.name===categoryGroupName)?.id??0);return <>
<h2>{t("action.edit_tag")}</h2>
<label>{t("label.name")}<input maxLength={groups.find(group=>group.id===groupId)?.name===authorGroupName?200:5} value={name} onChange={e=>setName(e.target.value)}/>
</label>
<label>{t("label.group")}<select value={groupId} onChange={e=>setGroupId(Number(e.target.value))}>{groups.map(group=>
<option value={group.id} key={group.id}>{group.name}</option>)}</select>
</label>
<button className="primary full" onClick={()=>void api(`/api/tags/${tag.id}`,token,{method:"PUT",body:JSON.stringify({name,group_id:groupId})}).then(done)}>{t("action.save")}</button>
</>}

function NotificationPanel({token,close}:{token:string;close:()=>void}){const notices=useQuery({queryKey:["notifications"],queryFn:()=>api<{items:{id:number;title:string;details:string;createdAt:string;read:boolean}[];unread:number}>("/api/notifications",token)});const replacements=useQuery({queryKey:["replacements"],queryFn:()=>api<{workId:number;fileName:string}[]>("/api/replacements",token)});const[confirmClear,setConfirmClear]=useState(false);const[selectedIds,setSelectedIds]=useState<number[]>([]);useEffect(()=>{void api("/api/notifications/read",token,{method:"POST"})},[token]);async function refresh(){await Promise.all([notices.refetch(),replacements.refetch()])}async function removeSelected(){await Promise.all(selectedIds.map(id=>api(`/api/notifications/${id}`,token,{method:"DELETE"})));setSelectedIds([]);await notices.refetch()}return <Modal close={close} wide>
<CardHeader title={t("label.notifications")} close={close}/>
<div className="notification-actions">
<button disabled={!selectedIds.length} onClick={()=>void removeSelected()}>{t("action.delete_selected_notifications")}</button>
<button onClick={()=>setConfirmClear(true)}>{t("action.clear_notifications")}</button>
</div>
<div className="notification-list">{replacements.data?.map(item=>
<article className="notification-row unread" key={`r${item.workId}`}>
<div>
<strong>{tf("replacement.mobile_title",{file_name:item.fileName})}</strong>
<small>{t("label.must_process_before_reopen")}</small>
</div>
<div className="row-actions">
<button onClick={()=>void api(`/api/replacements/${item.workId}?preserve_metadata=true`,token,{method:"POST"}).then(refresh)}>{t("label.retain_metadata")}</button>
<button onClick={()=>void api(`/api/replacements/${item.workId}?preserve_metadata=false`,token,{method:"POST"}).then(refresh)}>{t("label.treat_as_new_work")}</button>
</div>
</article>)}{notices.data?.items.map(item=>
<article className={`notification-row selectable ${item.read?"read":"unread"} ${selectedIds.includes(item.id)?"selected-row":""}`} key={item.id} onClick={()=>setSelectedIds(values=>values.includes(item.id)?values.filter(id=>id!==item.id):[...values,item.id])}>
<div>
<strong>{item.title}</strong>
<small>{new Date(item.createdAt).toLocaleString()}</small>
</div>
<span className="selection-dot"/>
</article>)}{Array.from({length:Math.max(0,6-(notices.data?.items.length??0)-(replacements.data?.length??0))}).map((_,index)=>
<div className="notification-row placeholder" key={`p${index}`}/>)}</div>{confirmClear&&<Modal close={()=>setConfirmClear(false)} warning>
<h2>{t("confirm.clear_all_notifications_title")}</h2>
<p>{t("error.irreversible_after_clear")}</p>
<div className="split-actions">
<button onClick={()=>setConfirmClear(false)}>{t("action.cancel")}</button>
<button className="danger" onClick={()=>void api("/api/notifications/all",token,{method:"DELETE"}).then(()=>{setConfirmClear(false);setSelectedIds([]);return notices.refetch()})}>{t("confirm.confirm_clear")}</button>
</div>
</Modal>}</Modal>}

function SettingsPanel({token,close,disconnect,languageChanged}:{token:string;close:()=>void;disconnect:()=>void;languageChanged:()=>void}){const[theme,setTheme]=useState(()=>localStorage.getItem("hmanga-theme")??"system");const[language,setLanguage]=useState(()=>localStorage.getItem("hmanga-language")??"zh-CN");const languages=useQuery({queryKey:["locales"],queryFn:()=>api<Language[]>("/api/locales",token)});const device=useQuery({queryKey:["current-device"],queryFn:()=>api<{name:string}>("/api/devices/me",token)});const computer=useQuery({queryKey:["computer"],queryFn:()=>api<{computerName:string}>("/api/library/status",token)});const version=useQuery({queryKey:["version"],queryFn:()=>api<{version:string}>("/api/version",token)});function change(value:string){setTheme(value);localStorage.setItem("hmanga-theme",value);document.documentElement.dataset.theme=value}async function changeLanguage(value:string){const next=await api<Record<string,string>>(`/api/locales/${encodeURIComponent(value)}`,token);localStorage.setItem("hmanga-language",value);setLanguage(value);setMessages(next);languageChanged()}return <Modal close={close}>
<CardHeader title={t("label.settings")} close={close}/>
<div className="settings-stack">
<div className="info-box">
<small>{t("label.current_computer")}</small>
<strong>{computer.data?.computerName??t("status.reading")}</strong>
</div>
<div className="info-box">
<small>{t("label.current_device")}</small>
<strong>{device.data?.name??t("status.reading")}</strong>
</div>
<label>{t("label.appearance_theme")}<select value={theme} onChange={e=>change(e.target.value)}>
<option value="system">{t("label.follow_system")}</option>
<option value="light">{t("label.light_theme")}</option>
<option value="dark">{t("label.dark_theme")}</option>
</select>
</label>
<label>{t("label.interface_language")}<select value={language} onChange={e=>void changeLanguage(e.target.value)}>
{languages.data?.map(item=><option value={item.code} key={item.code}>{item.name}</option>)}
</select>
</label>
<p className="software-version muted">{tf("software.version",{version:version.data?.version??"…"})}</p>
<button className="danger-outline" onClick={disconnect}>{t("label.disconnect_current_computer")}</button>
</div>
</Modal>}

function Library({token,disconnect,languageRevision,languageChanged}:{token:string;disconnect:()=>void;languageRevision:number;languageChanged:()=>void}){void languageRevision;const queryClient=useQueryClient();const restored=useRef(loadLibraryView()).current;const lastRevision=useRef(-1);const[input,setInput]=useState(restored.input);const[search,setSearch]=useState(restored.search);const[page,setPage]=useState(restored.page);const[selected,setSelected]=useState<Work|null>(restored.selected);const[reading,setReading]=useState(restored.reading);const[showFilters,setShowFilters]=useState(restored.showFilters);const[filters,setFilters]=useState<Filters>(restored.filters);const[showNotifications,setShowNotifications]=useState(restored.showNotifications);const[showSettings,setShowSettings]=useState(restored.showSettings);const[sort,setSort]=useState(()=>localStorage.getItem("hmanga-sort")??"added");const[descending,setDescending]=useState(()=>localStorage.getItem("hmanga-sort-direction")!=="asc");const[unread,setUnread]=useState(0);const sharedState=useQuery({queryKey:["shared-state"],queryFn:()=>api<{revision:number;unread:number}>("/api/state",token),refetchInterval:500});useEffect(()=>{const state=sharedState.data;if(!state)return;setUnread(state.unread);if(lastRevision.current>=0&&state.revision!==lastRevision.current)["works","detail","tags","filter-tags","manage-tags","manage-groups"].forEach(key=>void queryClient.invalidateQueries({queryKey:[key]}));lastRevision.current=state.revision},[sharedState.data,queryClient]);useEffect(()=>{let active=true;let checking=false;async function verify(){if(checking)return;checking=true;try{const response=await fetch("/api/devices/me",{headers:{Authorization:`Bearer ${token}`}});if(active&&response.status===401)disconnect()}catch{/* temporary network loss is not a revocation */}finally{checking=false}}const timer=window.setInterval(()=>void verify(),1000);const visible=()=>{if(document.visibilityState==="visible")void verify()};document.addEventListener("visibilitychange",visible);void verify();return()=>{active=false;window.clearInterval(timer);document.removeEventListener("visibilitychange",visible)}},[token,disconnect]);const previousInput=useRef(input);useEffect(()=>{if(input===previousInput.current)return;previousInput.current=input;const timer=setTimeout(()=>{setSearch(input);setPage(1)},400);return()=>clearTimeout(timer)},[input]);useEffect(()=>{const save=()=>sessionStorage.setItem(libraryViewKey,JSON.stringify({input,search,page,selected,reading,showFilters,filters,showNotifications,showSettings,scrollY:window.scrollY}));save();window.addEventListener("pagehide",save);return()=>window.removeEventListener("pagehide",save)},[input,search,page,selected,reading,showFilters,filters,showNotifications,showSettings]);useEffect(()=>{if(restored.scrollY)requestAnimationFrame(()=>window.scrollTo({top:restored.scrollY}))},[restored.scrollY]);function goHome(){setInput("");setSearch("");setFilters(defaultFilters());setPage(1);setSelected(null);setReading(false);setShowFilters(false);setShowNotifications(false);setShowSettings(false);window.scrollTo({top:0})}const filterQuery=`&kinds=${filters.kinds.join(",")}&tag_ids=${filters.tagIds.join(",")}&tag_mode=${filters.tagMode}&rating_mode=${filters.ratingMode}&rating=${filters.rating}`;const works=useQuery({queryKey:["works",search,page,filters,sort,descending],queryFn:()=>api<WorkPage>(`/api/works?text=${encodeURIComponent(search)}&page=${page}&sort=${sort}&descending=${descending}${filterQuery}`,token)});if(works.error&&String(works.error).includes(t("label.pair")))disconnect();if(selected&&reading)return <MobileReader id={selected.id} title={selected.title} token={token} back={()=>setReading(false)}/>;return <main className="library">
<header className="app-bar">
<div className="brand">
<button className="brand-home" aria-label={t("action.home_and_clear_filters")} onClick={goHome}>
<span className="brand-mark small">H</span>
</button>
<strong>HManガ</strong>
</div>
<div className="app-actions">
<button className="icon-button badge-host" aria-label={t("label.notifications")} onClick={()=>{setShowNotifications(true);setUnread(0)}}>
<Icon name="bell"/>{unread>0&&<span className="badge">{unread>99?"99+":unread}</span>}</button>
<button className="icon-button" aria-label={t("label.settings")} onClick={()=>setShowSettings(true)}>
<Icon name="settings"/>
</button>
</div>
</header>
<section className="home-content">
<div className="search-row">
<input placeholder={t("message.search_all_fields")} value={input} onChange={e=>setInput(e.target.value)}/>
<button className="icon-button" aria-label={t("label.filter")} onClick={()=>setShowFilters(true)}>
<Icon name="filter"/>
</button>
</div>
<div className="sort-row">
<select value={sort} onChange={e=>{setSort(e.target.value);localStorage.setItem("hmanga-sort",e.target.value);setPage(1)}}>
<option value="added">{t("label.recently_added")}</option>
<option value="file_name">{t("label.file_name_or_number")}</option>
<option value="title">{t("label.title")}</option>
<option value="rating">{t("label.rating")}</option>
</select>
<button onClick={()=>setDescending(value=>{localStorage.setItem("hmanga-sort-direction",!value?"desc":"asc");return!value})}>{descending?t("label.descending"):t("label.ascending")}</button>
<span className="result-count">{tf("works.short_count",{count:works.data?.total??0})}</span>
</div>{works.isPending&&<div className="loading">{t("status.loading")}</div>}{works.isError&&<p className="error-box">{works.error.message}</p>}<section className="works">{works.data?.items.map(work=>
<article className="work" key={work.id} onClick={()=>setSelected(work)}>
<div className="cover">
<AuthImage path={`/api/works/${work.id}/thumbnail?v=${encodeURIComponent(work.coverVersion)}`} token={token}/>
</div>
<div className="meta">
<h2>{work.title}</h2>
<p className="work-number">{work.kind==="comic"?work.number||"":work.fileName}</p>
<div className="tags">
<span className="system-tag">{work.kind==="comic"?t("label.comic"):t("label.illustration")}</span>{work.tags.slice(0,4).map(tag=>
<span className={tagClass(tag)} key={tag.id}>{tag.name}</span>)}{work.tags.length>4&&<span className="ungrouped">+{work.tags.length-4}</span>}</div>
<p className="stars">{"★".repeat(work.rating)}{"☆".repeat(3-work.rating)}</p>
</div>
</article>)}</section>{works.data&&<nav className="pages">
<button disabled={page===1} onClick={()=>setPage(page-1)}>‹</button>
<form onSubmit={e=>e.preventDefault()}>
<input aria-label={t("action.jump_to_page")} inputMode="numeric" value={page} onChange={e=>setPage(Math.min(works.data.pages,Math.max(1,Number(e.target.value)||1)))}/>
</form>
<span>/ {works.data.pages}</span>
<button disabled={page===works.data.pages} onClick={()=>setPage(page+1)}>›</button>
</nav>}</section>{selected&&<div className="detail-overlay">
<DetailView id={selected.id} token={token} back={()=>setSelected(null)} read={()=>setReading(true)} filter={(kind,tagId)=>{setInput("");setSearch("");setFilters({kinds:[kind],tagIds:tagId===null?[]:[tagId],tagMode:"all",ratingMode:"any",rating:0});setPage(1);setSelected(null)}}/>
</div>}{showFilters&&<FilterPanel token={token} value={filters} change={value=>{setFilters(value);setPage(1)}} close={()=>setShowFilters(false)}/>} {showNotifications&&<NotificationPanel token={token} close={()=>setShowNotifications(false)}/>} {showSettings&&<SettingsPanel token={token} close={()=>setShowSettings(false)} disconnect={disconnect} languageChanged={languageChanged}/>}</main>}

export default function App(){const[token,setToken]=useState(()=>localStorage.getItem(tokenKey)??"");const[languageRevision,setLanguageRevision]=useState(0);useEffect(()=>{document.documentElement.dataset.theme=localStorage.getItem("hmanga-theme")??"system"},[]);useEffect(()=>{const code=localStorage.getItem("hmanga-language")??"zh-CN";if(!token||code==="zh-CN")return;void api<Record<string,string>>(`/api/locales/${encodeURIComponent(code)}`,token).then(messages=>{setMessages(messages);setLanguageRevision(value=>value+1)}).catch(()=>{localStorage.setItem("hmanga-language","zh-CN")})},[token]);const disconnect=useCallback(()=>{if(token)void fetch("/api/devices/me",{method:"DELETE",headers:{Authorization:`Bearer ${token}`}});localStorage.removeItem(tokenKey);sessionStorage.removeItem(libraryViewKey);setToken("")},[token]);return token?<Library token={token} disconnect={disconnect} languageRevision={languageRevision} languageChanged={()=>setLanguageRevision(value=>value+1)}/>:<Pair onPaired={setToken}/>}
