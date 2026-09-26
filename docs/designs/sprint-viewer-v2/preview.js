/* Standalone review prototype; persistence is local to this browser only. */
(() => {
  'use strict';
  const {issues,rules,trends}=window.SprintSample;
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const storeKey='scrum-sprint-viewer-v2-preview';
  const defaults=()=>({assessment:'Not assessed',assessmentNote:'',reviewNote:'',actions:[],dismissed:[]});
  let saved=defaults();
  try { const raw=JSON.parse(localStorage.getItem(storeKey)); if(raw&&Array.isArray(raw.actions)&&Array.isArray(raw.dismissed)) saved={...saved,...raw}; } catch { /* Private browsing can disable storage. */ }
  const initialRole=new URLSearchParams(location.search).get('view');
  const state={tab:'overview',filter:'all',query:'',role:window.SprintReview.configs[initialRole]?initialRole:'Team',focus:'all',person:'Alex',cohort:null,evidence:null,page:0,sort:1,suggestionState:'open'};
  const pageSize=6;
  let editing=null,toastTimer;
  const original=issues.filter(i=>i.original),done=issues.filter(i=>i.done),unfinished=issues.filter(i=>!i.done&&!i.removed),added=issues.filter(i=>!i.original),removed=issues.filter(i=>i.removed),originalDone=original.filter(i=>i.done),originalUnfinished=original.filter(i=>!i.done&&!i.removed);
  const points=rows=>rows.reduce((sum,i)=>sum+i.points,0);
  const median=values=>{const s=[...values].sort((a,b)=>a-b);return s.length?s.length%2?s[Math.floor(s.length/2)]:(s[s.length/2-1]+s[s.length/2])/2:null;};
  const percentile=(values,p)=>{const s=[...values].sort((a,b)=>a-b);return s.length?s[Math.ceil(s.length*p)-1]:null;};
  function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
  function persist(){try{localStorage.setItem(storeKey,JSON.stringify(saved));return true;}catch{toast('Browser storage is unavailable. Changes last only for this page.');return false;}}
  const ruleState=rule=>saved.actions.some(a=>a.ruleId===rule.id)?'action':saved.dismissed.includes(rule.id)?'dismissed':'open';
  function badge(issue){const cls=issue.done?'done':issue.removed?'removed':issue.status==='Blocked'?'blocked':'review';return `<span class="badge ${cls}">${esc(issue.status)}</span>`;}
  function summary(){
    const ratio=Math.round(originalDone.length/original.length*100);
    const metrics=[['Planned',`${original.length} issues`,`${points(original)} pts`,'original'],['Plan completed',`${ratio}%`,`${originalDone.length} of ${original.length} issues`,'originalDone'],['Total completed',`${done.length} issues`,`${points(done)} pts`,'done'],['Unfinished at close',`${unfinished.length} issues`,`${points(unfinished)} pts`,'unfinished'],['Scope change',`<b class="plus">+${added.length}</b> / <b class="minus">−${removed.length}</b>`,'issues · additions / removals','changed']];
    $('metrics').innerHTML=metrics.map(([name,value,sub,filter])=>`<button class="metric" data-quick="${filter}" aria-label="${name}: ${value.replace(/<[^>]+>/g,'')}. View issues"><span>${name}</span><strong>${value}</strong><small>${sub}</small></button>`).join('');
    const sets=[['Completed',originalDone,'originalDone'],['Unfinished',originalUnfinished,'originalUnfinished'],['Removed',original.filter(i=>i.removed),'removed']];
    $('plan-bar').innerHTML=sets.map(([name,rows,filter])=>`<button data-quick="${filter}" style="width:${rows.length/original.length*100}%" aria-label="${rows.length} original issues ${name.toLowerCase()}">${Number((rows.length/original.length*100).toFixed(1))}%</button>`).join('');
    $('bar-legend').innerHTML=sets.map(([name,rows],n)=>`<div class="legend-item"><i class="dot ${n===1?'amber':n===2?'gray':''}"></i><div>${name}<span>${rows.length} issues</span></div></div>`).join('');
    $('added-line').textContent=`Added work: ${added.filter(i=>i.done).length} completed · ${added.filter(i=>!i.done&&!i.removed).length} unfinished`;
    $('discussion-list').innerHTML=rules.map((r,n)=>`<button class="discussion" data-discussion="${r.id}"><i class="dot ${n<2?'amber':'gray'}"></i><span>${r.short(r.keys.length)}</span><span class="arrow">›</span></button>`).join('');
  }
  function selectTab(tab,updateUrl=true){
    if(!['overview','suggestions','flow','trends','retro'].includes(tab)){tab='overview';updateUrl=location.hash!=='#main';}
    state.tab=tab;document.body.dataset.tab=tab;
    document.querySelectorAll('[role=tab]').forEach(b=>{const active=b.dataset.tab===tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
    document.querySelectorAll('[role=tabpanel]').forEach(p=>p.hidden=p.id!==`panel-${tab}`);
    $('work').hidden=tab!=='overview';
    if(updateUrl)history.replaceState(null,'',`#${tab}`);
    if(tab==='suggestions')renderSuggestions();
    if(tab==='retro')renderRetro();
  }
  function clearIssueScope(){state.evidence=null;state.cohort=null;state.query='';state.focus='all';state.filter='all';state.page=0;$('search').value='';$('issue-focus').value='all';}
  function quickFilter(filter){clearIssueScope();state.filter=filter;selectTab('overview');renderIssues();$('work').scrollIntoView({block:'start'});}
  function reviewLens(applyFocus=true){
    $('review-role').value=state.role;
    if(applyFocus){clearIssueScope();state.focus=window.SprintReview.configs[state.role].focus;$('issue-focus').value=state.focus;}
    window.SprintReview.render(state.role,saved,state.person);renderIssues();renderSuggestions();
    const url=new URL(location.href);url.searchParams.set('view',state.role);history.replaceState(null,'',url.pathname+url.search+url.hash);
  }
  const filterLabels={all:'All work',original:'Original plan',added:'Added',removed:'Removed',unfinished:'Unfinished',done:'Completed',originalDone:'Completed original work',originalUnfinished:'Unfinished original work',changed:'Added or removed'};
  function filteredIssues(){
    const query=state.query.toLowerCase().trim();
    const evidence=state.evidence?rules.find(r=>r.id===state.evidence):null;
    return issues.filter(i=>{
      if(evidence&&!evidence.keys.includes(i.key))return false;
      if(state.cohort&&!state.cohort.keys.includes(i.key))return false;
      if(state.focus==='person'&&i.assignee!==state.person)return false;
      if(state.focus==='stories'&&i.type!=='Story')return false;
      if(state.focus==='unfinished'&&(i.done||i.removed))return false;
      const predicates={all:true,original:i.original,added:!i.original,removed:i.removed,unfinished:!i.done&&!i.removed,done:i.done,originalDone:i.original&&i.done,originalUnfinished:i.original&&!i.done&&!i.removed,changed:!i.original||i.removed};
      return predicates[state.filter]&&(!query||`${i.key} ${i.summary} ${i.assignee}`.toLowerCase().includes(query));
    }).sort((a,b)=>a.key.localeCompare(b.key)*state.sort);
  }
  function renderIssues(){
    const rows=filteredIssues(),pages=Math.max(1,Math.ceil(rows.length/pageSize));state.page=Math.min(state.page,pages-1);
    if($('issue-group').value==='developer')rows.sort((a,b)=>a.assignee.localeCompare(b.assignee)||a.key.localeCompare(b.key)*state.sort);
    const visible=rows.slice(state.page*pageSize,(state.page+1)*pageSize);
    $('issues').innerHTML=visible.length?visible.map(i=>`<tr><td><button class="issue-link" data-issue="${i.key}">${i.key}</button></td><td>${esc(i.summary)}</td><td>${i.type}</td><td><span class="avatar" aria-hidden="true">${i.assignee.slice(0,2).toUpperCase()}</span>${i.assignee}</td><td>${i.original?'Original':'Added'}</td><td>${badge(i)}</td><td>${i.points}</td></tr>`).join(''):'<tr><td colspan="7" class="empty">No issues match these filters. Clear filters to see all work.</td></tr>';
    if($('issue-group').value==='developer'){
      let previous=null;
      [...$('issues').children].forEach((row,index)=>{const issue=visible[index];if(!issue||previous===issue.assignee)return;previous=issue.assignee;const group=rows.filter(i=>i.assignee===issue.assignee);const heading=document.createElement('tr');heading.className='past-group-row';const cell=document.createElement('td');cell.colSpan=7;cell.textContent=`${issue.assignee} · ${group.length} matching issues · ${points(group)} pts at start/entry · assignee at close/removal`;heading.appendChild(cell);row.before(heading);});
    }
    $('issue-count').textContent=`${rows.length} issues`;
    $('page-label').textContent=rows.length?`Showing ${state.page*pageSize+1}–${Math.min((state.page+1)*pageSize,rows.length)} of ${rows.length} issues`:'0 matching issues';
    $('prev-page').disabled=state.page===0;$('next-page').disabled=state.page>=pages-1;
    $('issue-filters').innerHTML=['all','original','added','removed','unfinished'].map(f=>`<button data-filter="${f}" aria-pressed="${state.filter===f}">${filterLabels[f]}</button>`).join('');
    const context=[];
    if(state.evidence)context.push(`Evidence for ${state.evidence}: ${rules.find(r=>r.id===state.evidence).category}`);
    if(state.filter!=='all')context.push(filterLabels[state.filter]);
    if(state.cohort)context.push(`Metric evidence: ${state.cohort.label}`);
    if(state.focus==='person')context.push(`Selected developer: ${state.person} at close/removal`);
    else if(state.focus==='stories')context.push('Issue focus: stories');
    else if(state.focus==='unfinished')context.push('Issue focus: unfinished at close');
    if(state.query)context.push(`Search: ${state.query}`);
    $('filter-context').hidden=!context.length;$('filter-context').querySelector('span').textContent=context.join(' · ');
  }
  function showEvidence(id){clearIssueScope();state.evidence=id;$('work').hidden=false;renderIssues();$('work').scrollIntoView({block:'start'});$('work').querySelector('h2').tabIndex=-1;$('work').querySelector('h2').focus({preventScroll:true});}
  function renderSuggestions(){
    const counts={open:0,action:0,dismissed:0};rules.forEach(r=>counts[ruleState(r)]++);
    $('suggestion-count').textContent=counts.open;
    $('suggestion-states').innerHTML=[['open','Open'],['action','Action created'],['dismissed','Dismissed']].map(([key,label])=>`<button data-suggestion-state="${key}" aria-pressed="${state.suggestionState===key}">${label} <span class="count">${counts[key]}</span></button>`).join('');
    const roleOrder={'Team':['SV-01','SV-02','SV-03'],'Developer':['SV-01','SV-03','SV-02'],'PO / BA':['SV-02','SV-03','SV-01'],'Scrum Master':['SV-03','SV-01','SV-02'],'Engineering Manager':['SV-03','SV-02','SV-01']};
    $('role-explanation').textContent=`${state.role} view: discussion prompts and priority reflect this role. Rule facts and evidence always cover the team; use Overview for role-specific metrics.`;
    const visible=rules.filter(r=>ruleState(r)===state.suggestionState).sort((a,b)=>roleOrder[state.role].indexOf(a.id)-roleOrder[state.role].indexOf(b.id));
    $('suggestion-list').innerHTML=visible.length?visible.map(r=>`<article class="suggestion surface" id="suggestion-${r.id}"><div class="suggestion-meta"><span>${r.category}</span><span>${r.id} · At sprint close</span></div><h3>${r.title(r.keys.length)}</h3><p>${r.next}</p><p class="role-prompt"><strong>${esc(state.role)} discussion:</strong> ${esc(window.SprintReview.prompt(state.role,r.id))}</p><div class="suggestion-controls"><button data-evidence="${r.id}">View ${r.keys.length} issues</button>${ruleState(r)==='action'?'<button class="primary" data-go="retro">View action</button>':`<button class="primary" data-action="${r.id}">Create action</button>`}${ruleState(r)==='open'?`<button class="text-button" data-dismiss="${r.id}">Dismiss</button>`:ruleState(r)==='dismissed'?`<button class="text-button" data-restore="${r.id}">Restore</button>`:''}</div><details><summary>Why this appears</summary><p><strong>${r.id} · Rule version 1 · Sample configuration 1</strong><br>${r.why}<br>Evidence: ${r.keys.join(', ')}. This observation does not establish a cause.</p></details></article>`).join(''):'<div class="surface empty">No suggestions in this view. Check the other views or continue reviewing the sprint.</div>';
  }
  function openIssue(key){
    const i=issues.find(row=>row.key===key);if(!i)return;
    const firstActive=i.original?({219:'13 Aug 2026',220:'20 Aug 2026',221:'22 Aug 2026',222:'14 Aug 2026'}[Number(i.key.slice(4))]||'17 Aug 2026'):i.addedAt==='2026-08-27'?'27 Aug 2026':'24 Aug 2026';
    $('detail-body').innerHTML=`<p class="issue-key">${i.key}</p><h2 id="detail-title">${esc(i.summary)}</h2><p>${badge(i)} <span class="muted">${i.type} · ${i.epic}</span></p><dl class="context-list"><div><dt>Assignee ${i.removed?'at removal':'at close'}</dt><dd>${i.assignee}</dd></div><div><dt>Scope</dt><dd>${i.original?'Original plan':'Added during sprint'}</dd></div><div><dt>${i.original?'Start':'Entry'} estimate</dt><dd>${i.points} points</dd></div><div><dt>${i.removed?'Removal':'Closing'} estimate</dt><dd>${i.points} points</dd></div><div><dt>Goal linkage</dt><dd>${i.goalLinked?"Explicit sample link":"Not linked in sample"}</dd></div><div><dt>Acceptance</dt><dd>${esc(i.acceptance||"Not applicable to sample type")}</dd></div><div><dt>Scope-change reason</dt><dd>${esc(i.scopeReason||"Not recorded")}</dd></div><div><dt>Evidence basis</dt><dd>Synthetic complete history</dd></div></dl><h3>Recorded timeline</h3><ol class="timeline"><li><small>${i.original?'17 Aug 2026, 09:00':i.addedAt==='2026-08-27'?'27 Aug 2026, 09:00':'24 Aug 2026, 09:00'}</small>${i.original?'Present at sprint start':'Added to Sprint 24'}</li><li><small>${firstActive}</small>First active-state entry${i.consecutiveCloses===2?' · work started before this sprint':''}</li>${i.reopened?'<li><small>During Sprint 24</small>Done → In progress · reopened once</li>':''}<li><small>${i.removed?'25 Aug 2026':'28 Aug 2026, 18:00'}</small>${i.removed?'Removed from sprint':`Sprint closes · ${i.status}`}</li></ol>${i.cycleDays?`<p><strong>Elapsed cycle time:</strong> ${i.cycleDays} days, from first active state to completion. Completion occurred before or at sprint close.</p>`:''}${i.ageDays?`<p><strong>Age at close:</strong> ${i.ageDays} elapsed days.</p>`:''}<p class="footnote">Illustrative event summary. The production drawer will use timestamped Jira events with field-level coverage. No cause is inferred from these events.</p>`;
    $('detail-dialog').showModal();
  }
  function renderFlow(){
    const cycles=done.map(i=>i.cycleDays),reopened=issues.filter(i=>i.reopened);
    const metrics=[['Cycle time · median',`${median(cycles)} days`,`${done.length} completed issues`],['Cycle time · P85',`${percentile(cycles,.85)} days`,'Nearest-rank · 21 issues'],['Reopened work',`${reopened.length} issue`,'Done → unfinished during sprint'],['Recorded blocked time','Unavailable','Interval evidence not included in preview']];
    $('flow-metrics').innerHTML=metrics.map(([label,value,sub])=>`<div class="flow-metric"><span>${label}</span><strong>${value}</strong><small>${sub}</small></div>`).join('');
    $('stage-bars').innerHTML=[['In progress','activeDays'],['In review','reviewDays'],['In testing','testDays']].map(([label,key])=>{const value=median(done.map(i=>i[key]));return `<div class="stage-row"><span>${label}</span><div class="stage-track"><span style="width:${value/5*100}%"></span></div><strong>${Number(value.toFixed(2))}d</strong></div>`;}).join('');
    $('aging').innerHTML=[...unfinished].sort((a,b)=>b.ageDays-a.ageDays).slice(0,3).map(i=>`<div class="aging-row"><div><button class="issue-link" data-issue="${i.key}">${i.key}</button><small> · ${i.status}</small></div><strong>${i.ageDays} days</strong></div>`).join('');
  }
  function renderTrends(){
    $('trend-bars').innerHTML=trends.map(t=>`<div class="trend-column"><strong>${t.done}</strong><div class="bar" style="height:${t.done/30*150}px" role="img" aria-label="Sprint ${t.sprint}: ${t.done} completed issues"></div><span>Sprint ${t.sprint}</span></div>`).join('');
    const baseline=median(trends.slice(0,-1).map(t=>t.done));
    $('trend-context').textContent=`Sprint 24: 21 completed issues · Previous five-sprint median: ${baseline} issues. Sample values, not a forecast.`;
    $('trend-rows').innerHTML=trends.map(t=>`<tr><td>Sprint ${t.sprint}${t.sprint===24?' · selected':''}</td><td>${t.planned}</td><td>${Math.round(t.originalDone/t.planned*100)}% <span class="muted">(${t.originalDone}/${t.planned})</span></td><td>${t.done}</td><td>+${t.added} / −${t.removed}</td><td>${t.median} days</td></tr>`).join('');
  }
  function renderRetro(){
    window.SprintReview.render(state.role,saved,state.person);
    $('assessment-label').textContent=saved.assessment;$('assess').textContent=saved.assessment==='Not assessed'?'Add assessment':'Edit assessment';
    $('retro-assessment').textContent=saved.assessment;
    $('retro-note').textContent=saved.assessmentNote||'No assessment note yet. The team can record the outcome and supporting evidence.';
    $('review-note').value=saved.reviewNote;
    $('action-count').textContent=`${saved.actions.length} ${saved.actions.length===1?'action':'actions'} · ${saved.actions.filter(a=>a.status==='Done').length} done`;
    $('actions').innerHTML=saved.actions.length?saved.actions.map(a=>`<div class="action-row"><div><strong>${esc(a.title)}</strong><p>${esc(a.owner)} · Due ${esc(a.due)}${a.ruleId?` · From ${esc(a.ruleId)}`:' · Team-created'} · Preview</p></div><label><span class="muted">Status </span><select aria-label="Status for ${esc(a.title)}" data-action-status="${esc(a.id)}">${['Open','In progress','Done'].map(s=>`<option${a.status===s?' selected':''}>${s}</option>`).join('')}</select></label></div>`).join(''):'<div class="empty">No actions yet. Add one here or create an action from a suggestion.</div>';
  }
  function assessmentForm(){
    editing={type:'assessment'};$('edit-title').textContent='Assess the sprint goal';
    $('edit-body').innerHTML=`<p class="muted">A team assessment, independent of point completion.</p><label>Assessment<select name="assessment">${['Not assessed','Achieved','Partially achieved','Not achieved'].map(s=>`<option${saved.assessment===s?' selected':''}>${s}</option>`).join('')}</select></label><label>Note and evidence<textarea name="note" rows="4" maxlength="2000" placeholder="Record the outcome and supporting review or demo evidence.">${esc(saved.assessmentNote)}</textarea></label>`;$('edit-dialog').showModal();
  }
  function actionForm(ruleId){const rule=rules.find(r=>r.id===ruleId);editing={type:'action',ruleId:rule?.id||null};$('edit-title').textContent='Create an improvement action';$('edit-body').innerHTML=`<p class="muted">${rule?`From ${rule.id} · ${rule.keys.length} supporting issues`:'A team-created retrospective action'}</p><label>Action<input name="title" required maxlength="180" value="${esc(rule?.action||'')}" placeholder="What will the team do?"></label><label>Owner<input name="owner" required maxlength="80" placeholder="Choose a responsible person"></label><label>Due date<input name="due" type="date" required></label><p class="footnote">Saved in this browser only. This does not create a Jira issue.</p>`;$('edit-dialog').showModal();}
  function exportCsv(){const rows=filteredIssues();const cell=v=>{let s=String(v??'');if(/^[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};const csv=[['Design preview — synthetic data only'],['Sprint','24'],['View',state.role],['Issue focus',state.focus],['Evidence',state.cohort?.label||state.evidence||'None'],['Basis','At sprint close; points at start/entry; removed rows at removal'],['Key','Summary','Type','Assignee','Scope','Closing/removal state','Points'],...rows.map(i=>[i.key,i.summary,i.type,i.assignee,i.original?'Original':'Added',i.status,i.points])].map(row=>row.map(cell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='sprint-24-sample-filtered.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`Exported ${rows.length} sample issues using current table filters.`);}
  document.addEventListener('click',e=>{
    const button=e.target.closest('button');if(!button)return;
    if(button.dataset.tab)selectTab(button.dataset.tab);
    if(button.dataset.go)selectTab(button.dataset.go);
    if(button.dataset.quick)quickFilter(button.dataset.quick);
    if(button.dataset.filter){state.filter=button.dataset.filter;state.page=0;renderIssues();}
    if(button.dataset.issue)openIssue(button.dataset.issue);
    if(button.hasAttribute('data-assess-goal'))assessmentForm();
    if(button.dataset.cohort){const cohort=window.SprintReview.getCohort(button.dataset.cohort);if(cohort){clearIssueScope();state.cohort=cohort;selectTab('overview');renderIssues();$('work').scrollIntoView({block:'start'});$('work').querySelector('h2').tabIndex=-1;$('work').querySelector('h2').focus({preventScroll:true});}}
    if(button.dataset.evidence)showEvidence(button.dataset.evidence);
    if(button.dataset.action)actionForm(button.dataset.action);
    if(button.dataset.suggestionState){state.suggestionState=button.dataset.suggestionState;renderSuggestions();}
    if(button.dataset.dismiss){saved.dismissed.push(button.dataset.dismiss);persist();renderSuggestions();toast('Suggestion dismissed. Restore it from the Dismissed view.');}
    if(button.dataset.restore){saved.dismissed=saved.dismissed.filter(id=>id!==button.dataset.restore);persist();renderSuggestions();toast('Suggestion restored to Open.');}
    if(button.dataset.discussion){state.suggestionState=ruleState(rules.find(r=>r.id===button.dataset.discussion));selectTab('suggestions');$(`suggestion-${button.dataset.discussion}`)?.scrollIntoView({block:'center'});}
    if(button.hasAttribute('data-close'))button.closest('dialog').close();
  });
  $('edit-form').addEventListener('submit',e=>{e.preventDefault();const data=new FormData(e.target);if(editing.type==='assessment'){saved.assessment=data.get('assessment');saved.assessmentNote=data.get('note').trim();}else {const title=data.get('title').trim(),owner=data.get('owner').trim();if(!title||!owner){toast('Enter an action and an owner.');return;}saved.actions.push({id:crypto.randomUUID?crypto.randomUUID():String(Date.now()),title,owner,due:data.get('due'),status:'Open',ruleId:editing.ruleId});}const stored=persist();$('edit-dialog').close();renderRetro();renderSuggestions();if(stored)toast(editing.type==='assessment'?'Assessment saved in this browser.':'Action created. Find it in Retrospective.');});
  $('assess').onclick=assessmentForm;$('edit-assessment').onclick=assessmentForm;$('new-action').onclick=()=>actionForm(null);
  $('save-note').onclick=()=>{saved.reviewNote=$('review-note').value.trim();if(persist())toast('Review note saved in this browser.');};
  $('actions').addEventListener('change',e=>{if(!e.target.dataset.actionStatus)return;const action=saved.actions.find(a=>a.id===e.target.dataset.actionStatus);action.status=e.target.value;if(persist())toast('Action status updated in this browser.');renderRetro();});
  $('search').addEventListener('input',e=>{state.query=e.target.value;state.page=0;renderIssues();});
  $('review-role').onchange=e=>{state.role=e.target.value;reviewLens();};
  $('review-person').onchange=e=>{state.person=e.target.value;reviewLens();};
  $('issue-focus').onchange=e=>{state.focus=e.target.value;state.cohort=null;state.evidence=null;state.page=0;renderIssues();};
  $('issue-group').onchange=()=>{state.page=0;renderIssues();};
  $('clear-filters').onclick=()=>{clearIssueScope();renderIssues();};
  $('prev-page').onclick=()=>{state.page--;renderIssues();};$('next-page').onclick=()=>{state.page++;renderIssues();};
  $('sort-key').onclick=()=>{state.sort*=-1;state.page=0;$('sort-key').textContent=`Key ${state.sort===1?'↑':'↓'}`;renderIssues();};
  $('definitions').onclick=()=>$('definition-dialog').showModal();$('export').onclick=exportCsv;
  $('reset-preview').onclick=()=>{saved=defaults();persist();renderRetro();renderSuggestions();toast('Preview notes, actions and dismissals reset.');};
  document.querySelector('.tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('[role=tab]')],current=tabs.indexOf(document.activeElement);const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(current+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;selectTab(tabs[next].dataset.tab);tabs[next].focus();});
  window.addEventListener('hashchange',()=>selectTab(location.hash.slice(1),false));
  summary();renderIssues();renderFlow();renderTrends();renderRetro();reviewLens();selectTab(location.hash.slice(1)||'overview',false);
})();
