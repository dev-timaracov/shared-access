import './style.css';
import {outcomes,groupReports,escapeHtml as e} from './data.js';
const app = document.querySelector('#app');
let token = '', generation = 0;
const date = value => value ? new Date(value).toLocaleString('ru-RU') : 'Нет снимка';
const empty = text => `<div class="empty">${e(text)}</div>`;
const badge = text => `<span class="badge">${e(text || 'Не задан')}</span>`;
async function api(path, body) {
  const response = await fetch(`/api${path}`,{method:body ? 'POST' : 'GET',headers:{...(token ? {Authorization:`Bearer ${token}`} : {}),...(body ? {'Content-Type':'application/json'} : {})},...(body ? {body:JSON.stringify(body)} : {})});
  if (!response.ok) {
    const body = await response.json().catch(()=>({}));
    throw new Error(response.status === 401 ? 'Токен недействителен. Откройте подключение и введите токен.' : `${response.status}: ${body.detail || 'Не удалось загрузить данные'}`);
  }
  return response.json();
}
function shell() {
  app.innerHTML = `<aside><a class="brand" href="#">◈ <span>Shared Access<small>КОНТЕКСТ КОМАНДЫ</small></span></a><a class="nav" href="#">▦ Проекты</a><div class="aside-note">Один проект.<br>Общая история работы.</div><button id="connection">Подключение</button></aside><main><header><span>Рабочее пространство</span><span class="status">● REST API</span></header><div id="content" aria-live="polite"></div></main><dialog id="login"><form id="credentials"><h2>Подключение к Shared Access</h2><p>Персональный bearer-токен. Хранится только в памяти этой вкладки.</p><label>Токен<input name="token" type="password" autocomplete="off" placeholder="В режиме --no-auth оставьте пустым"></label><div class="actions"><button type="button" id="cancel">Отмена</button><button class="primary">Подключиться</button></div></form></dialog>`;
  document.querySelector('#connection').onclick = ()=>document.querySelector('#login').showModal();
  document.querySelector('#cancel').onclick = ()=>document.querySelector('#login').close();
  document.querySelector('#credentials').onsubmit = event=>{event.preventDefault();token=new FormData(event.target).get('token').trim();event.target.reset();document.querySelector('#login').close();render();};
}
const content = ()=>document.querySelector('#content');
function title(kicker,heading,description='') {return `<div class="page-heading"><div class="eyebrow">${e(kicker)}</div><h1>${e(heading)}</h1><p>${e(description)}</p></div>`;}
function info(label,value) {return `<div class="info"><small>${e(label)}</small><div>${e(value ?? 'Не задано')}</div></div>`;}
function taskCards(project,tasks) {
  return tasks.length ? `<div class="task-list">${tasks.map(t=>`<a class="task-row" href="#/projects/${project.id}/tasks/${encodeURIComponent(t.id)}"><span class="task-mark">↗</span><div><small>${e(t.external_id)}</small><h3>${e(t.snapshot.name || t.external_id)}</h3><small>${e(t.freshness === 'live' ? 'Из трекера' : 'Кеш')} · ${e(date(t.fetched_at))}</small></div><div>${badge(t.snapshot.state_id)}<small>${e(t.snapshot.priority || '')}</small></div><span>→</span></a>`).join('')}</div>` : empty('Задач пока нет. Синхронизируйте проект через API или MCP.');
}
async function render() {
  const current = ++generation;
  content().innerHTML = empty('Загрузка…');
  try {
    const parts = location.hash.slice(1).split('/').filter(Boolean);
    if (!parts.length) {
      const projects = await api('/projects');
      if (current !== generation) return;
      content().innerHTML = title('ОБЗОР','Проекты','Контекст, задачи и отчёты вашей команды в одном месте.')+`<div class="section-title"><h2>Все проекты</h2>${badge(projects.length)}</div><div class="project-grid">${projects.map(p=>`<a class="project-card" href="#/projects/${p.id}"><div class="card-top"><span class="project-icon">${e(p.name.slice(0,1).toUpperCase())}</span><span>↗</span></div><small>${e(p.slug)}</small><h2>${e(p.name)}</h2><p>${p.repositories.length} репозиториев</p><div class="tags">${p.repositories.map(r=>badge(r)).join('')}</div></a>`).join('')}</div>`+(projects.length ? '' : empty('Нет доступных проектов. Проверьте область доступа токена.'));
      return;
    }
    if (parts[0] !== 'projects' || !parts[1]) throw new Error('Страница не найдена');
    const project = await api(`/projects/${encodeURIComponent(parts[1])}`);
    if (current !== generation) return;
    if (parts[2] === 'tasks' && parts[3]) {
      const task = project.tasks.find(t=>t.id === decodeURIComponent(parts[3]));
      if (!task) throw new Error('Задача не найдена в проекте');
      let reports=[], events=[], cursor=null;
      content().innerHTML = `<a class="back" href="#/projects/${project.id}">← ${e(project.name)}</a>`+title(task.external_id,task.snapshot.name || 'Задача',task.snapshot.description_stripped || 'Описание отсутствует в сохранённом снимке.')+`<div class="stats">${info('Статус',task.snapshot.state_id)}${info('Приоритет',task.snapshot.priority)}${info('Кеш обновлён',date(task.fetched_at))}</div><p class="notice">Текущий статус задаёт таск-трекер. Здесь показан сохранённый снимок. История изменений содержит только наблюдаемые события; данные Git и проверок из отчётов не проверены по CI.</p><details><summary>Все поля задачи</summary><pre>${e(JSON.stringify(task.snapshot,null,2))}</pre></details><div id="history"></div>`;
      const draw = () => {
        const buckets=groupReports(reports), max=Math.max(1,...buckets.map(b=>b.total));
        document.querySelector('#history').innerHTML = `<div class="section-title"><h2>График отчётов</h2>${badge(`${reports.length} загружено`)}</div><p class="muted">Число отчётов по дням (UTC), по загруженной истории.</p><div class="legend">${Object.entries(outcomes).map(([key,label])=>`<span><i class="${key}"></i>${label}</span>`).join('')}</div>`+(buckets.length ? `<div class="chart" role="img" aria-label="Количество отчётов по дням"><div class="bars">${buckets.map(b=>`<div class="bar-column"><strong>${b.total}</strong><div class="bar-stack" style="height:${b.total/max*160}px" title="${e(b.day)}: ${b.total} отчётов">${Object.keys(outcomes).map(key=>`<div class="${key}" style="height:${b[key]/b.total*100}%" title="${e(outcomes[key])}: ${b[key]}"></div>`).join('')}</div><small>${e(b.day)}</small></div>`).join('')}</div></div><details><summary>Данные графика</summary><table><thead><tr><th>Дата</th>${Object.values(outcomes).map(v=>`<th>${v}</th>`).join('')}<th>Всего</th></tr></thead><tbody>${buckets.map(b=>`<tr><td>${b.day}</td>${Object.keys(outcomes).map(k=>`<td>${b[k]}</td>`).join('')}<td>${b.total}</td></tr>`).join('')}</tbody></table></details>` : empty('Отчётов пока нет.'))+`<div class="section-title"><h2>Изменения</h2>${badge('Последние 20 событий')}</div>`+(events.length ? events.map(v=>`<article class="event">${info(date(v.created_at),v.actor)}<pre>${e(JSON.stringify(v.payload,null,2))}</pre></article>`).join('') : empty('Наблюдаемые изменения не зафиксированы.'))+`<div class="section-title"><h2>Отчёты о работе</h2></div>`+(reports.length ? reports.map(r=>`<article class="report"><div class="report-meta">${badge(outcomes[r.outcome] || r.outcome)}<span>${e(date(r.created_at))} · ${e(r.developer_id)}</span></div><h3>${e(r.summary)}</h3>${['decisions','blockers','next_steps'].map((key,i)=>r[key]?.length ? `<h4>${['Решения','Блокировки','Следующие шаги'][i]}</h4><ul>${r[key].map(v=>`<li>${e(v)}</li>`).join('')}</ul>` : '').join('')}<details><summary>Полный отчёт · непроверенные сведения агента</summary><pre>${e(JSON.stringify(r,null,2))}</pre></details></article>`).join('') : empty('История работы пуста.'))+(cursor ? '<button id="more">Загрузить предыдущие отчёты</button>' : '');
        if (cursor) document.querySelector('#more').onclick=load;
      };
      const load = async()=>{
        const button=document.querySelector('#more'); if(button) button.disabled=true;
        try {
          const page=await api(`/tasks/${task.id}/history?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
          if(current !== generation) return;
          reports.push(...page.reports);events=page.recent_events;cursor=page.next_cursor;draw();
        } catch(error) {if(current === generation){if(button)button.disabled=false;document.querySelector('#history').insertAdjacentHTML('beforeend',`<p role="alert" class="error">${e(error.message)}</p>`);}}
      };
      await load(); return;
    }
    content().innerHTML = `<a class="back" href="#">← Все проекты</a>`+title(project.slug,project.name,'Информация о проекте и накопленная история задач.')+`<div class="stats">${info('Трекер',project.tracker_provider)}${info('Workspace',project.tracker_workspace)}${info('Проект трекера',project.tracker_project_id)}</div><section><h2>Репозитории</h2><div class="tags">${project.repositories.map(badge).join('') || 'Не добавлены'}</div><details><summary>Разрешённые переходы статусов</summary><pre>${e(JSON.stringify(project.allowed_transitions,null,2))}</pre></details></section><section><h2>Документы по точным ревизиям</h2>${project.documents.map(d=>`<button class="document" data-doc="${d.id}"><b>${e(d.path)}</b><small>${e(d.repo)} · ${e(d.ref)}</small></button>`).join('') || empty('Документов пока нет.')}<div id="doc-content"></div></section><div class="section-title"><h2>Задачи</h2><button id="live">Получить задачи из трекера</button></div><p class="muted">Зарегистрированные задачи · сохранённые снимки, не текущий статус трекера</p><div id="tasks">${taskCards(project,project.tasks)}</div>`;
    document.querySelector('#live').parentElement.insertAdjacentHTML('beforeend','<button id="new-task" class="primary">Добавить задачу</button>');
    content().insertAdjacentHTML('beforeend',`<dialog id="task-dialog"><form id="task-form"><h2>Новая задача</h2><p>Задача появится в трекере и в истории проекта.</p><label>Название<input name="name" required maxlength="255"></label><label>Описание<textarea name="description" maxlength="100000" rows="6"></textarea></label><label>Приоритет<select name="priority"><option value="none">Не задан</option><option value="low">Низкий</option><option value="medium">Средний</option><option value="high">Высокий</option><option value="urgent">Срочный</option></select></label><p id="task-error" role="alert" class="error"></p><div class="actions"><button type="button" id="task-cancel">Отмена</button><button class="primary" id="task-submit">Создать</button></div></form></dialog>`);
    const dialog=document.querySelector('#task-dialog');
    document.querySelector('#new-task').onclick=()=>dialog.showModal();
    document.querySelector('#task-cancel').onclick=()=>dialog.close();
    let creating=false;
    dialog.addEventListener('cancel',event=>{if(creating)event.preventDefault();});
    document.querySelector('#task-form').onsubmit=async event=>{
      event.preventDefault();
      if(creating)return;
      const data=Object.fromEntries(new FormData(event.target));
      data.name=data.name.trim();
      if(!data.name){document.querySelector('#task-error').textContent='Введите название задачи.';return;}
      creating=true;
      const submit=document.querySelector('#task-submit'), cancel=document.querySelector('#task-cancel');
      submit.disabled=cancel.disabled=true;
      document.querySelector('#task-error').textContent='';
      try {
        const task=await api(`/projects/${project.id}/tasks/create`,data);
        if(current!==generation)return;
        dialog.close();location.hash=`#/projects/${project.id}/tasks/${task.id}`;
      } catch(error) {
        if(current===generation)document.querySelector('#task-error').textContent=`${error.message} При ошибке соединения проверьте список задач в трекере перед повторным созданием.`;
      } finally {creating=false;submit.disabled=cancel.disabled=false;}
    };
    document.querySelectorAll('[data-doc]').forEach(button=>button.onclick=async()=>{
      button.disabled=true;
      try {const d=await api(`/documents/${button.dataset.doc}`);if(current===generation)document.querySelector('#doc-content').innerHTML=`<h3>${e(d.path)}</h3><pre>${e(d.content)}</pre>`;}catch(error){if(current===generation)document.querySelector('#doc-content').innerHTML=`<p class="error" role="alert">${e(error.message)}</p>`;}finally{button.disabled=false;}
    });
    document.querySelector('#live').onclick=async event=>{
      event.target.disabled=true;
      try {
        let cursor=null, tasks=[], seen=new Set();
        do {
          const page=await api(`/projects/${project.id}/tasks?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
          if(current!==generation)return;
          tasks.push(...page.tasks.map(snapshot=>({snapshot,fetched_at:page.fetched_at,local:project.tasks.find(t=>t.external_id===snapshot.id)})));
          cursor=page.next_cursor;
          if(cursor && seen.has(cursor))throw new Error('Трекер вернул повторный курсор');
          seen.add(cursor);
        }while(cursor);
        document.querySelector('#tasks').innerHTML=tasks.length ? `<div class="task-list">${tasks.map(t=>t.local ? taskCards(project,[{...t.local,snapshot:t.snapshot,fetched_at:t.fetched_at,freshness:'live'}]) : `<article class="task-row"><div><small>${e(t.snapshot.id)}</small><h3>${e(t.snapshot.name)}</h3><p>Нет локальной истории. Для отчётов зарегистрируйте задачу через API/MCP.</p><details><summary>Информация</summary><pre>${e(JSON.stringify(t.snapshot,null,2))}</pre></details></div>${badge(t.snapshot.state_id)}</article>`).join('')}</div>` : empty('В трекере нет задач.');
      } catch(error){if(current===generation)document.querySelector('#tasks').insertAdjacentHTML('afterbegin',`<p class="error" role="alert">${e(error.message)}</p>`);}finally{event.target.disabled=false;}
    };
  } catch(error) {if(current===generation)content().innerHTML=`${title('SHARED ACCESS','Не удалось открыть страницу')}<p role="alert" class="error">${e(error.message)}</p><button id="retry">Повторить</button>`; const retry=document.querySelector('#retry');if(retry)retry.onclick=render;}
}
shell();window.addEventListener('hashchange',render);render();
