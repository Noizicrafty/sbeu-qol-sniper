"use strict";
let advancedLoaded=false;
function importWikiHtml(){document.querySelector('#wiki-html-file').click();}
function renderAdvanced(value){
  if(!advancedLoaded){for(const key of ['overlay_labels','overlay_outlines','protect_surplus','hideout_fir_required'])$('#advanced-'+key).checked=value.settings[key];for(const key of ['color_needed','color_surplus','color_uncertain','color_other'])$('#advanced-'+key).value=value.settings[key];advancedLoaded=true;}
  const library=value.library||{};$('#library-progress').max=Math.max(1,library.total||1);$('#library-progress').value=library.ready||library.indexed||0;
  $('#library-status').textContent=`Индекс изображений: ${library.indexed||0} / ${library.total||value.catalog_total}. ${library.running?'Подготовка в фоне…':''}`;
  $('#library-errors').textContent=library.failed?`Ошибок загрузки: ${library.failed}`:'';
  const calibrations=Object.entries(value.calibration||{});$('#calibration-summary').innerHTML=calibrations.map(([key,c])=>`<p><strong>${esc(key)}</strong> · клетка ${c.cell} px · масштаб ${Math.round(c.ui_scale*100)}%</p>`).join('')||'<p>Калибровка появится при открытии инвентаря в Tarkov.</p>';
  const stash=value.stash_scan||{};$('#stash-status').textContent=`${stash.active?'● Сбор схрона идёт':'Сбор схрона остановлен'} · кадров: ${stash.frames||0} · окон ящиков: ${stash.containers||0} · видимых объектов: ${stash.items||0}. ${stash.warning||''}`;
}
document.addEventListener('DOMContentLoaded',()=>{
  $('#overlay-colors').innerHTML=[['color_needed','Нужные'],['color_surplus','Излишки'],['color_uncertain','Неопределённые'],['color_other','Прочие']].map(([key,label])=>`<label>${label}<input type="color" id="advanced-${key}"></label>`).join('');
  $('#advanced-form').addEventListener('submit',event=>{event.preventDefault();const data={};for(const key of ['overlay_labels','overlay_outlines','protect_surplus','hideout_fir_required'])data[key]=$('#advanced-'+key).checked;for(const key of ['color_needed','color_surplus','color_uncertain','color_other'])data[key]=$('#advanced-'+key).value;perform(()=>post('settings',data),'Настройки сохранены');});
  const input=document.createElement('input');input.type='file';input.id='wiki-html-file';input.accept='.html,.htm';input.hidden=true;document.body.append(input);input.addEventListener('change',()=>{if(input.files[0])perform(async()=>post('wiki-html',{html:await input.files[0].text()}),'HTML передан приложению');input.value='';});
});
