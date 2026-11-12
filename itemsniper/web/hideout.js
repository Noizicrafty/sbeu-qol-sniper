'use strict';
let hideoutAssets = null, hideoutPresentation = null, mapResizeObserver, hoverStation = null;
const keyOf = name => String(name).toLowerCase().replace(/[^a-z0-9]+/g,'');
function referenceModule(name) {return hideoutAssets?.modules.find(module=>keyOf(module.name)===keyOf(name));}
function referenceStation(name) {return state.stations.find(station=>keyOf(station.name)===keyOf(name));}
function stationLabel(station) {return referenceModule(station.name)?.label || station.name_ru || station.name;}
function stationIcon(station, level=null, status='') {
  const svg=referenceModule(station.name)?.svg || '<svg viewBox="0 0 39 39" aria-hidden="true"><polygon points="19.5 1.5 3.91 10.5 3.91 28.5 19.5 37.5 35.09 28.5 35.09 10.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  return `<span class="market-icon ${status}">${svg}${level!==null?`<span class="lvl">${String(level).padStart(2,'0')}</span>`:''}</span>`;
}
function levelPresentation(station,level) {
  const source=Object.entries(hideoutPresentation?.stations||{}).find(([name])=>keyOf(name)===keyOf(station.name));
  return source?.[1].find(entry=>entry.level===level)||{};
}
function prerequisiteStatus(prerequisite) {
  const match=prerequisite.label.match(/^(.*?)\s*(\d+)$/);
  if(!match)return {className:'',text:prerequisite.label};
  const reference=hideoutAssets.modules.find(module=>module.label.trim().toLowerCase()===match[1].trim().toLowerCase());
  const station=reference&&referenceStation(reference.name);
  const current=station?state.levels[station.name]:undefined;
  return {className:current!==undefined&&current>=Number(match[2])?'built':'locked',text:prerequisite.label,station};
}
function levelIsLocked(station,level) {
  return (levelPresentation(station,level).prerequisites||[]).some(p=>prerequisiteStatus(p).className==='locked');
}
function buildCard(station,upgrade,{popup=false}={}) {
  const level=upgrade.level,current=state.levels[station.name]??-1,complete=current>=level;
  const presentation=levelPresentation(station,level),locked=levelIsLocked(station,level);
  const owned={};for(const snapshot of Object.values(state.inventory))for(const [name,value] of Object.entries(snapshot))owned[name]=(owned[name]||0)+(typeof value==='number'?value:value.count);
  const money=upgrade.items.filter(req=>['Roubles','Dollars','Euros'].includes(req.name));
  const labelKey=value=>String(value).toLowerCase().replace(/[^\p{L}\p{N}]/gu,'').replace(/ё/g,'е');
  const displayItems=presentation.items||[];
  const visualItem=req=>displayItems.find(entry=>labelKey(entry.label)===labelKey(item(req.name).name_ru));
  const itemOrder=req=>{const index=displayItems.indexOf(visualItem(req));return index<0?999:index;};
  const items=upgrade.items.filter(req=>!['Roubles','Dollars','Euros'].includes(req.name)).sort((a,b)=>itemOrder(a)-itemOrder(b));
  const currency={Roubles:'₽',Dollars:'$',Euros:'€'};
  const cost=presentation.cost;
  return `<article class="market-card" data-card-level="${level}"><div><div class="market-card-header">${stationIcon(station,level,complete?'complete':locked?'locked':'')}<div><div class="market-card-level">Уровень ${level}</div><div class="market-card-title">${esc(stationLabel(station))}</div></div></div><div class="card-block">Время постройки: <span class="card-value">${esc(presentation.time||'Нет данных')}</span></div><div class="card-block"><div class="block-label">Бонусы:</div>${presentation.bonuses?.length?`<ul>${presentation.bonuses.map(text=>`<li>${esc(text)}</li>`).join('')}</ul>`:'<div class="card-unknown">Не импортированы</div>'}</div><div class="card-block"><div class="block-label">Требуется:</div>${money.map(req=>`<div class="card-value">${req.count.toLocaleString('ru-RU')}${currency[req.name]}</div>`).join('')}${(presentation.prerequisites||[]).map(p=>{const status=prerequisiteStatus(p);return `<div class="card-prerequisite ${status.className}">${status.station?referenceModule(status.station.name)?.svg||'':''}<span>${esc(status.text)}</span></div>`;}).join('')}${station.requirements_missing?'<div class="card-unknown">Требования вики не загружены</div>':''}<div class="card-items">${items.map(req=>`<div class="card-item ${(owned[req.name]||0)>=req.count?'fulfilled':''}" title="${esc(item(req.name).name_ru)} · есть ${owned[req.name]||0}, нужно ${req.count}"><img src="/api/grid?name=${encodeURIComponent(req.name)}" alt="${esc(item(req.name).name_ru)}" style="width:${visualItem(req)?.width||40}px;height:${visualItem(req)?.height||40}px" loading="lazy">${req.fir&&state.settings.hideout_fir_required?'<span class="card-fir" title="Найдено в рейде">✓</span>':''}<div class="card-item-count">×${req.count}</div></div>`).join('')}</div></div></div><div><div>Стоимость постройки: <span class="card-price" title="Справочная оценка Tarkov Market на ${esc(hideoutPresentation?.captured||'дату импорта')}; не обновляется в реальном времени">${esc(cost||'Нет данных')}</span></div><div class="card-actions"><button class="market-button build ${locked?'locked':''}" data-build-station="${esc(station.name)}" data-level="${level}" ${complete?'disabled':''}>Построить</button><button class="market-button" data-demolish-station="${esc(station.name)}" data-level="${level}" ${current<level?'disabled':''}>Снести</button></div>${!popup&&state.hideout_candidate.levels[station.name]!==undefined?`<div class="card-ocr">С экрана: уровень ${state.hideout_candidate.levels[station.name]} · проверьте текущий уровень<br><button class="market-button" data-confirm-station="${esc(station.name)}">Подтвердить</button></div>`:''}</div></article>`;
}
function renderMap() {
  if(!hideoutAssets)return;
  const signature=JSON.stringify([state.stations,state.levels,state.hideout_candidate.levels,selectedStation,state.settings.hideout_fir_required,state.inventory]);
  if(signature===lastMap)return;lastMap=signature;
  $('#map-nodes').innerHTML=hideoutAssets.modules.map(module=>{
    const station=referenceStation(module.name);if(!station)return '';
    const current=state.levels[station.name],next=station.levels.find(l=>l.level===(current??0)+1);
    const ready=current!==undefined&&next&&!levelIsLocked(station,next.level);
    const status=selectedStation===station.name?'selected':ready?'ready':(current??0)===0?'not_built':'';
    return `<button class="market-module ${status}" style="left:${module.x}px;top:${module.y}px" data-station="${esc(station.name)}" aria-label="${esc(module.label)}" title="${esc(module.label)} · ${current===undefined?'не считано':'уровень '+current}">${module.svg}${current>0?`<span class="lvl">${String(current).padStart(2,'0')}</span>`:''}${state.hideout_candidate.levels[station.name]!==undefined?'<span class="candidate-dot"></span>':''}</button>`;
  }).join('');
  $('#map-nodes').querySelectorAll('[data-station]').forEach(button=>{
    button.addEventListener('click',()=>{selectedStation=selectedStation===button.dataset.station?undefined:button.dataset.station;$('#module-popup').hidden=true;hoverStation=null;lastMap='';renderMap();});
    button.addEventListener('mouseenter',()=>showModulePopup(button.dataset.station,button));
    button.addEventListener('focus',()=>showModulePopup(button.dataset.station,button));
    button.addEventListener('mouseleave',event=>{if(!event.relatedTarget?.closest('#module-popup'))hideModulePopup();});
    button.addEventListener('blur',()=>hideModulePopup());
  });
  const mobile=$('#mobile-station');
  if(document.activeElement!==mobile){mobile.innerHTML='<option value="">—</option>'+hideoutAssets.modules.map(module=>{const station=referenceStation(module.name);if(!station)return '';return `<option value="${esc(station.name)}">${esc(module.label)} · ${state.levels[station.name]===undefined?'Не считано':'Уровень '+state.levels[station.name]}</option>`;}).join('');mobile.value=selectedStation||'';}
  renderDetail();
}
function renderDetail() {
  const station=state.stations.find(s=>s.name===selectedStation);
  if(!station){$('#station-detail').innerHTML='';return;}
  $('#station-detail').innerHTML=station.levels.map(upgrade=>buildCard(station,upgrade)).join('');
}
function showModulePopup(name,button) {
  if(selectedStation===name)return;
  const station=state.stations.find(s=>s.name===name);if(!station)return;
  const current=state.levels[name]??0;
  const upgrade=station.levels.find(l=>l.level===current+1)||station.levels.at(-1);if(!upgrade)return;
  hoverStation=name;const popup=$('#module-popup');popup.innerHTML=buildCard(station,upgrade,{popup:true});
  const module=referenceModule(name);popup.style.left=(module.x>510?module.x-280:module.x+48)+'px';popup.style.top=(module.y+10)+'px';popup.hidden=false;
}
function hideModulePopup() {setTimeout(()=>{const popup=$('#module-popup');if(!popup.matches(':hover')&&!popup.contains(document.activeElement)){popup.hidden=true;hoverStation=null;}},50);}
function fillSettingsLevels() {
  const station=state.stations.find(s=>s.name===$('#settings-station').value);if(!station)return;
  const current=state.levels[station.name]??-1,maximum=Math.max(0,...station.levels.map(l=>l.level));
  $('#settings-level').innerHTML='<option value="-1">Не считано</option>'+Array.from({length:maximum+1},(_,n)=>`<option value="${n}">${n===0?'0 · Не построено':'Уровень '+n}</option>`).join('');$('#settings-level').value=String(current);
}
function openHideoutSettings(name) {
  const select=$('#settings-station');select.innerHTML=state.stations.map(station=>`<option value="${esc(station.name)}">${esc(stationLabel(station))}</option>`).join('');select.value=name||selectedStation||state.stations[0]?.name;fillSettingsLevels();$('#hideout-settings').showModal();
}
document.addEventListener('DOMContentLoaded',async()=>{
  $('#open-hideout-settings').addEventListener('click',()=>state&&openHideoutSettings());
  document.querySelectorAll('[data-close-hideout]').forEach(button=>button.addEventListener('click',()=>$('#hideout-settings').close()));
  $('#open-scanner-settings').addEventListener('click',()=>{$('#hideout-settings').close();changePage('settings');});
  $('#settings-station').addEventListener('change',fillSettingsLevels);
  $('#save-settings-level').addEventListener('click',()=>perform(()=>post('levels',{levels:{[$('#settings-station').value]:Number($('#settings-level').value)}}),'Уровень сохранён. Для применения целей — F10'));
  $('#mobile-station').addEventListener('change',()=>{selectedStation=$('#mobile-station').value||undefined;lastMap='';renderMap();});
  $('#module-popup').addEventListener('mouseleave',()=>{$('#module-popup').hidden=true;hoverStation=null;});
  document.addEventListener('click',event=>{
    const build=event.target.closest('[data-build-station]'),demolish=event.target.closest('[data-demolish-station]'),confirm=event.target.closest('[data-confirm-station]');
    if(build)perform(()=>post('levels',{levels:{[build.dataset.buildStation]:Number(build.dataset.level)}}),'Модуль и обязательные зависимости отмечены построенными. Для целей — F10');
    if(demolish)perform(()=>post('levels',{levels:{[demolish.dataset.demolishStation]:Number(demolish.dataset.level)-1}}),'Модуль и зависимые улучшения пересчитаны. Для целей — F10');
    if(confirm)perform(()=>post('levels',{levels:{[confirm.dataset.confirmStation]:state.hideout_candidate.levels[confirm.dataset.confirmStation]}}),'Уровень с экрана подтверждён');
  });
  try{
    const responses=await Promise.all([fetch('/assets/hideout-reference.json'),fetch('/assets/hideout-details.json')]);
    if(responses.some(response=>!response.ok))throw Error('Не удалось загрузить локальную схему убежища');
    [hideoutAssets,hideoutPresentation]=await Promise.all(responses.map(response=>response.json()));
    $('#market-outline').innerHTML=hideoutAssets.outline;
    const resize=()=>{const width=$('.hideout-schema').clientWidth;if(width){const scale=width/800;$('.hideout-canvas').style.transform=`scale(${scale})`;$('.hideout-schema').style.height=700*scale+'px';}};
    mapResizeObserver=new ResizeObserver(resize);mapResizeObserver.observe($('.hideout-schema'));resize();
    if(state){lastMap='';renderMap();}
  }catch(error){toast(error.message,true);}
});
