'use strict';
const $ = (selector) => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtTime = seconds => seconds ? new Date(seconds * 1000).toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
let state, token, selectedStation, currentPage = 'hideout', targetItem, pollBusy = false;
let lastMaterials = '', lastMap = '', lastInventory = '', lastPublished = '', lastManual = '', lastCandidate = '', lastRegions = '';
let searchSerial = 0, toastTimer, searchTimer, settingsLoaded = false;
const records = new Map();
const names = {hideout:'Убежище',items:'Предметы для поиска',inventory:'Мой инвентарь',scanner:'Сканер экрана',quests:'Квесты',settings:'Настройки'};
function toast(text, error=false) { $('#toast').textContent=text; $('#toast').classList.toggle('error',error); $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,4500); }
async function post(path,data) {
  if (!token) throw Error('Нет соединения с приложением');
  const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-ItemSniper-Token':token},body:JSON.stringify(data)});
  const body=await response.json(); if(!response.ok) throw Error(body.error||'Ошибка запроса'); return body;
}
async function perform(job, message) { try { await job(); if(message)toast(message); await poll(); } catch(e) { toast(e.message,true); } }
function action(name) { if(name==='import_html')return importWikiHtml();return perform(()=>post('action',{action:name}),'Команда передана приложению'); }
function item(name) { return records.get(name)||{name,name_ru:name,image:'/api/icon?name='+encodeURIComponent(name)}; }
function itemImage(name) { return `<img src="/api/icon?name=${encodeURIComponent(name)}" alt="" loading="lazy">`; }
function changePage(name) {
  if(!names[name])name='hideout';currentPage=name;
  for(const page of document.querySelectorAll('.page'))page.hidden=page.id!=='page-'+name;
  for(const button of document.querySelectorAll('[data-page]'))button.classList.toggle('active',button.dataset.page===name);
  $('#crumb').textContent=names[name];history.replaceState(null,'','#'+name);
  if(name==='items') searchItems();if(name==='quests'&&typeof loadQuests==='function')loadQuests();
  if(name==='scanner' && state) renderPublished();
}
document.addEventListener('click', event=>{
  const nav=event.target.closest('[data-page]'); if(nav) changePage(nav.dataset.page);
  const command=event.target.closest('[data-action]'); if(command) action(command.dataset.action);
});
// Hideout schema, popups and level cards are implemented in hideout.js.
function renderMaterials() {
  const signature=JSON.stringify(state.needed);if(signature===lastMaterials)return;lastMaterials=signature;
  const entries=Object.entries(state.needed).sort((a,b)=>b[1].remaining-a[1].remaining);
  $('#materials').innerHTML=entries.map(([name,n])=>`<tr><td class="item-cell">${itemImage(name)}<div><strong>${esc(item(name).name_ru)}</strong><span class="secondary">${esc(name)}</span></div></td><td>${n.required}</td><td>${n.owned}</td><td><strong>${n.remaining}</strong></td><td>${n.fir_required?`<span class="fir-badge">✓ ${n.fir_owned}/${n.fir_required}</span>`:'—'}</td><td>${esc(n.uses.join(' · '))}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Пока нет рассчитанных материалов. Укажите уровни и загрузите требования вики или добавьте ручные цели.</td></tr>';
}
function renderManual() {
  const signature=JSON.stringify(state.manual);if(signature===lastManual)return;lastManual=signature;
  const entries=Object.entries(state.manual);$('#manual-count').textContent=entries.length;
  $('#manual-targets').innerHTML=entries.map(([name,t])=>`<div class="manual-item"><h3>${esc(item(name).name_ru)}</h3><small>Количество: ${t.count}</small> ${t.fir?'<span class="fir-badge">✓ FIR</span>':''}<div class="item-actions"><button data-edit="${esc(name)}">Изменить</button><button data-remove="${esc(name)}">Убрать</button></div></div>`).join('')||'<div class="empty">Добавьте предметы из справочника слева</div>';
  $('#manual-targets').querySelectorAll('[data-edit]').forEach(b=>b.addEventListener('click',()=>openTarget(item(b.dataset.edit))));
  $('#manual-targets').querySelectorAll('[data-remove]').forEach(b=>b.addEventListener('click',()=>perform(()=>post('target',{name:b.dataset.remove,count:0,fir:false}),'Предмет убран из черновика')));
}
let itemPage=1,itemFilterLoaded=false;
async function searchItems(page=itemPage) {
  itemPage=page;const serial=++searchSerial;
  const params=new URLSearchParams({q:$('#item-search').value,page:String(page),limit:$('#item-per-page').value,category:$('#item-category').value,type:$('#item-type').value,sort:$('#item-sort').value,tracked:$('#item-tracked').checked?'1':'0'});
  try {
    const response=await fetch('/api/items?'+params);if(!response.ok)throw Error('Не удалось загрузить справочник');const body=await response.json();if(serial!==searchSerial)return;
    body.items.forEach(record=>records.set(record.name,record));itemPage=body.page;
    if(!itemFilterLoaded){$('#item-category').insertAdjacentHTML('beforeend',body.categories.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join(''));const labels={gun:'Оружие',ammo:'Патроны',mods:'Модификации',meds:'Медицина',provisions:'Еда и напитки',barter:'Бартер',container:'Контейнеры',keys:'Ключи',armor:'Броня',wearable:'Экипировка',preset:'Пресеты',quest:'Квестовые предметы',ammoBox:'Коробки патронов',armorPlate:'Бронепластины',backpack:'Рюкзаки',glasses:'Очки',grenade:'Гранаты',headphones:'Наушники',helmet:'Шлемы',injectors:'Инъекторы',markedOnly:'Меченые комнаты',noFlea:'Без барахолки',pistolGrip:'Пистолетные рукоятки',poster:'Плакаты',rig:'Разгрузки',specialSlot:'Специальные слоты',suppressor:'Глушители'};$('#item-type').insertAdjacentHTML('beforeend',body.types.map(t=>`<option value="${esc(t)}">${esc(labels[t]||t)}</option>`).join(''));itemFilterLoaded=true;}
    $('#search-count').textContent=`Найдено ${body.total} · всего ${body.catalog_total}`;
    $('#search-results').innerHTML=body.items.map(i=>`<article class="item-card">${itemImage(i.name)}<h3>${esc(i.name_ru)}</h3><small>${esc(i.name)}</small>${state?.quest_targets?.[i.name]?'<span class="quest-badge">◯ Для квеста</span>':''}<button class="button" data-add="${esc(i.name)}">+ В список поиска</button></article>`).join('')||'<div class="empty">По этим фильтрам ничего не найдено.</div>';
    $('#item-pagination').innerHTML=`<button class="button" id="items-prev" ${body.page<=1?'disabled':''}>← Назад</button><label>Страница <input id="items-page" type="number" min="1" max="${body.pages}" value="${body.page}" aria-label="Номер страницы предметов"> из ${body.pages}</label><button class="button" id="items-next" ${body.page>=body.pages?'disabled':''}>Далее →</button>`;
    $('#items-prev').onclick=()=>searchItems(itemPage-1);$('#items-next').onclick=()=>searchItems(itemPage+1);$('#items-page').onchange=e=>searchItems(Number(e.target.value));
    $('#search-results').querySelectorAll('[data-add]').forEach(b=>b.addEventListener('click',()=>openTarget(item(b.dataset.add))));
  } catch(e){toast(e.message,true);}
}
function openTarget(record) {targetItem=record;$('#target-title').textContent=record.name_ru;$('#target-english').textContent=record.name;$('#target-count').value=state.manual[record.name]?.count||1;$('#target-fir').checked=state.manual[record.name]?.fir||false;$('#target-dialog').showModal();}
$('#target-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{await post('target',{name:targetItem.name,count:Number($('#target-count').value),fir:$('#target-fir').checked});$('#target-dialog').close();},'Предмет сохранён. Для применения — F10');});
$('.dialog-close').addEventListener('click',()=>$('#target-dialog').close());
$('#item-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchItems(1),220);});
function renderInventory() {
  const signature=JSON.stringify([state.inventory_candidate,state.inventory]);if(signature===lastInventory)return;
  if(document.activeElement?.matches('#inventory-review input'))return;lastInventory=signature;
  const candidate=state.inventory_candidate;
  $('#inventory-review').innerHTML=`<h2>Проверка снимка ${candidate.at?'· '+fmtTime(candidate.at):''}</h2><p>Скан схрона собирает вещи при прокрутке. До подтверждения сохранённый инвентарь не меняется. ${esc(candidate.warning||'')}</p>${candidate.at?`<p class="inventory-hint">Проверьте стопки и галочку FIR. Неопределённые галочки не засчитываются.</p><form id="inventory-form"><div class="table-wrap"><table><thead><tr><th>ПРЕДМЕТ</th><th>ВСЕГО</th><th>ИЗ НИХ FIR</th><th>FIR НЕЯСЕН</th></tr></thead><tbody>${Object.entries(candidate.items).map(([name,v])=>`<tr data-inventory-name="${esc(name)}"><td>${esc(item(name).name_ru)}</td><td><input type="number" data-count min="0" value="${v.count}" aria-label="Всего ${esc(name)}" required></td><td><input type="number" data-fir min="0" value="${v.fir}" aria-label="FIR ${esc(name)}" required></td><td>${v.unknown||0}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Предметы в последнем кадре не распознаны. Не заменяйте непустой снимок, если это ошибка.</td></tr>'}</tbody></table></div><div class="inventory-name"><label for="snapshot-name">Имя снимка</label><input type="text" id="snapshot-name" value="Схрон" maxlength="80" required><select id="snapshot-scope" aria-label="Тип снимка"><option value="stash">Схрон</option></select><button type="submit" class="button primary">Подтвердить и заменить снимок</button></div></form>`:'<div class="empty">Откройте схрон в Tarkov, начните скан F9, прокрутите нужные области и завершите сбор.</div>'}`;
  $('#inventory-form')?.addEventListener('submit',e=>{e.preventDefault();const items={};$('#inventory-review').querySelectorAll('[data-inventory-name]').forEach(row=>items[row.dataset.inventoryName]={count:Number(row.querySelector('[data-count]').value),fir:Number(row.querySelector('[data-fir]').value)});perform(()=>post('inventory',{slot:$('#snapshot-name').value,items,scope:$('#snapshot-scope')?.value||'stash'}),'Инвентарь сохранён. Обновление целей — F10');});
  $('#saved-inventory').innerHTML=Object.entries(state.inventory).map(([slot,items])=>`<article class="panel saved-snapshot"><div class="panel-heading"><h2>${esc(slot)}</h2><button class="button small danger" data-delete-snapshot="${esc(slot)}">Удалить снимок</button></div>${Object.entries(items).map(([name,v])=>`<p>${esc(item(name).name_ru)} · ${typeof v==='number'?v:v.count} шт. · FIR ${typeof v==='number'?0:v.fir}</p>`).join('')||'<p>Пустой снимок</p>'}</article>`).join('')||'<div class="empty">Нет сохранённых снимков</div>';
  $('#saved-inventory').querySelectorAll('[data-delete-snapshot]').forEach(b=>b.addEventListener('click',()=>perform(()=>post('inventory/delete',{slot:b.dataset.deleteSnapshot}),'Снимок удалён')));
}
function renderPublished() {
  const signature=JSON.stringify([state.published_at,state.published]);if(signature===lastPublished)return;lastPublished=signature;
  $('#published-time').textContent='Список обновлён: '+fmtTime(state.published_at);
  $('#published-results').innerHTML=state.published.map(hit=>`<article class="found-card ${hit.status||'other'}">${itemImage(hit.name)}<div><h3>${esc(item(hit.name).name_ru)}</h3><p>${esc(hit.reason)} · осталось ${hit.remaining}</p><p>${Math.round(hit.score*100)}% · ${hit.method==='slot-image'?'изображение слота':'подпись слота'}</p>${hit.fir==='yes'?'<span class="fir-badge">✓ Найдено в рейде</span>':'<span class="unknown-badge">FIR не подтверждён</span>'}</div></article>`).join('')||'<div class="empty">В опубликованном списке пока нет совпадений. Откройте обыск в Tarkov и зафиксируйте результаты по F10.</div>';
}
function renderSettings(){
  $('#catalog-info').textContent=`Предметов: ${state.catalog_total}. Квестов: ${state.quest_count}. Сканирование включается только при фокусе Tarkov.`;
}
$('#all-levels').addEventListener('change',()=>perform(()=>post('settings',{all_levels:$('#all-levels').checked}),'Режим расчёта сохранён. Для применения — F10'));
async function poll() {
  if(pollBusy)return;pollBusy=true;
  try {
    const response=await fetch('/api/state');if(!response.ok)throw Error('Нет связи');state=await response.json();token=state.token;
    $('#connection-error').hidden=true;
    Object.values(state.items).forEach(record=>records.set(record.name,record));
    const health=state.health||{phase:'waiting',message:'Ожидание'};$('#scanner-status').textContent='● '+health.message;$('#scanner-status').dataset.phase=health.phase;
    $('#confirmed-stat').innerHTML=`${Object.keys(state.levels).length} <small>/ ${state.stations.length}</small>`;
    $('#target-stat').innerHTML=`${Object.values(state.needed).filter(n=>n.remaining>0).length} <small>предметов</small>`;
    $('#scan-stat').textContent=state.hideout_candidate.at?fmtTime(state.hideout_candidate.at):'Ещё не считано';
    $('#wiki-warning').hidden=!state.stations.some(s=>s.requirements_missing);
    $('#all-levels').checked=state.settings.all_levels;
    $('#status-text').textContent=state.status+(state.dirty?' · Есть изменения для F10':'');
    $('#scan-metrics').textContent=`Захват и проверка рамок: ${state.live?.fps||0} FPS · новый предмет: ${state.reveal?.new_item_ms??"—"} мс · общий проход: ${state.scan_ms} мс · активных целей: ${Object.keys(state.active_targets).length}`;
    const candidateSignature=JSON.stringify(state.hideout_candidate);
    if(candidateSignature!==lastCandidate){lastCandidate=candidateSignature;const candidates=Object.entries(state.hideout_candidate.levels);$('#ocr-review').hidden=!state.hideout_candidate.at;$('#ocr-review').innerHTML=`<span>⌖</span><div><b>Кандидаты OCR · ${fmtTime(state.hideout_candidate.at)}</b><p>${candidates.length?candidates.map(([name,level])=>`${esc(state.stations.find(s=>s.name===name)?.name_ru||name)}: ${level}`).join(' · '):'Уровни не определены. Можно указать их вручную.'}</p></div>`;}
    if(!document.activeElement?.matches('#station-detail select'))renderMap();
    renderMaterials();renderManual();renderInventory();renderPublished();renderSettings();if(typeof renderAdvanced==='function')renderAdvanced(state);if(typeof refreshQuests==='function')refreshQuests();
    const details=$('.debug-panel');if(details.open&&state.pending_at.loot){$('#frame-preview').hidden=false;$('#frame-preview').src='/api/frame?kind=loot&t='+state.sequence;}
  } catch(e){$('#connection-error').hidden=false;$('#scanner-status').textContent='● Приложение недоступно';$('#scanner-status').dataset.phase='error';} finally{pollBusy=false;}
}
document.addEventListener('keydown',event=>{if(event.repeat)return;const binding={F6:'quests_scan',F7:'toggle',F8:'hideout',F9:'stash_toggle',F10:'publish'}[event.key];if(binding){event.preventDefault();action(binding);}});
changePage(location.hash.slice(1));poll();setInterval(poll,800);

for(const id of ['item-category','item-type','item-sort','item-per-page','item-tracked'])$('#'+id).addEventListener('change',()=>searchItems(1));
$('#reset-item-filters').addEventListener('click',()=>{$('#item-search').value='';$('#item-category').value='';$('#item-type').value='';$('#item-tracked').checked=false;searchItems(1);});
