/* Review-only role lenses; calculations use the shared synthetic issue population. */
window.SprintReview = (() => {
  'use strict';
  const {issues,trends}=window.SprintSample;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const cohorts=new Map();
  const count=(rows,predicate)=>rows.filter(predicate).length;
  const isOpen=i=>!i.done&&!i.removed;
  const done=issues.filter(i=>i.done),added=issues.filter(i=>!i.original),removed=issues.filter(i=>i.removed),original=issues.filter(i=>i.original),unfinished=issues.filter(isOpen);
  const median=values=>{const s=values.filter(Number.isFinite).sort((a,b)=>a-b),m=Math.floor(s.length/2);return s.length?(s.length%2?s[m]:(s[m-1]+s[m])/2):null;};
  const pct=(n,d)=>d?`${(100*n/d).toFixed(1).replace(/\.0$/,'')}%`:'Unavailable';
  const days=v=>v===null?'Unavailable':`${Number(v.toFixed(1))}d`;
  const p85=values=>{const sorted=values.filter(Number.isFinite).sort((a,b)=>a-b);return sorted.length>=10?sorted[Math.ceil(sorted.length*.85)-1]:null;};
  function register(id,label,rows){cohorts.set(id,{label,keys:rows.map(i=>i.key)});return `data-cohort="${id}"`;}
  function link(id,label,rows){return `<button class="text-button" ${register(id,label,rows)}>${esc(label)} →</button>`;}
  function metric(label,value,note,rows,id){return `<${rows?'button':'div'} class="review-metric" ${rows?register(id,label,rows):''}><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}${rows?' · View issues →':''}</small></${rows?'button':'div'}>`;}
  function panel(title,subtitle,body){return `<section class="surface review-panel"><h3>${title}</h3><p class="muted">${subtitle}</p>${body}</section>`;}
  function table(headers,rows,label){return `<div class="table-scroll" tabindex="0" aria-label="${label}"><table class="review-table"><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}
  function scopePanel(){
    const changed=issues.filter(i=>!i.original||i.removed);
    return panel('Scope movement','Distinct issues; additions and final removals remain separate.',
      `<div class="scope-equation"><span>24<small>At start</small></span><b>+</b><span>5<small>Added</small></span><b>−</b><span>2<small>Removed</small></span><b>=</b><span>27<small>At close</small></span></div>`+
      table(['Issue','Change','Recorded reason'],changed.map(i=>`<tr><td><button class="issue-link" data-issue="${i.key}">${i.key}</button></td><td>${i.removed?'Removed':'Added'}</td><td>${esc(i.scopeReason||'Not recorded')}</td></tr>`),'Scope changes and recorded reasons')+
      `<p class="footnote">Gross movement: (5 + 2) / 24 = 29.2%. Net growth: (5 − 2) / 24 = 12.5%. No repeat membership events in this fixture.</p>`);
  }
  function contributionPanel(person){
    const names=person?[person]:[...new Set(issues.map(i=>i.assignee))].sort();
    const rows=names.map(name=>{
      const assigned=issues.filter(i=>i.assignee===name),retained=assigned.filter(i=>!i.removed),complete=assigned.filter(i=>i.done),pending=assigned.filter(isOpen),gone=assigned.filter(i=>i.removed);
      return `<tr><td>${link(`person-${name}`,name,assigned)}</td><td>${retained.length}</td><td>${link(`done-${name}`,String(complete.length),complete)} <small>(${complete.reduce((n,i)=>n+i.points,0)} pts)</small></td><td>${link(`open-${name}`,String(pending.length),pending)}</td><td>${gone.length}</td><td>${pct(complete.length,done.length)}</td><td>${['Story','Bug','Task'].map(t=>count(retained,i=>i.type===t)).join(' / ')}</td></tr>`;
    });
    return panel(person?`${esc(person)} · assigned work`:'Developer contribution · assignment context','Assignee at sprint close; removed items use assignee at removal.',
      table(['Developer','At close','Completed','Unfinished','Removed','Share of team completed','Story / Bug / Task at close'],rows,'Developer contribution at sprint close')+
      `<p class="footnote">Completed points use start/entry estimates. Share counts assigned completed tickets out of ${done.length} team completions. Pairing, reviews, testing and support can involve other people; these counts do not measure effort or individual productivity. Contributor and assignment-change histories are unavailable in this preview.</p>`);
  }
  function deliveryPanel(){
    return panel('Delivery by feature','Sprint scope within each feature, not the full epic backlog.',
      table(['Feature','Original','Added','Completed','Unfinished','Removed','Inspect'],[...new Set(issues.map(i=>i.epic))].map(epic=>{
        const rows=issues.filter(i=>i.epic===epic);
        return `<tr><td>${esc(epic)}</td><td>${count(rows,i=>i.original)}</td><td>${count(rows,i=>!i.original)}</td><td>${count(rows,i=>i.done)}</td><td>${count(rows,isOpen)}</td><td>${count(rows,i=>i.removed)}</td><td>${link(`epic-${epic.replace(/\W/g,'')}`,'Issues',rows)}</td></tr>`;
      }),'Feature delivery')+`<p class="footnote">Feature and goal links are explicit sample fields. Completion does not prove business impact or stakeholder acceptance.</p>`);
  }
  function flowPanel(){
    const rows=[...unfinished].sort((a,b)=>b.ageDays-a.ageDays);
    return panel('Unfinished work & repeated carryover','Age is frozen at close, measured from first active state.',
      table(['Issue','Stage at close','Age','Consecutive unfinished closes'],rows.map(i=>`<tr><td><button class="issue-link" data-issue="${i.key}">${i.key}</button></td><td>${i.status}</td><td>${i.ageDays}d</td><td>${i.consecutiveCloses}</td></tr>`),'Unfinished aging evidence')+
      `<p class="footnote">One issue is blocked at close. Recorded blocked duration and daily WIP are unavailable: interval history is not supplied. Unfinished work is not proof of assignment to the next sprint.</p>`);
  }
  function trendPanel(){
    const baseline=trends.slice(0,-1),values=baseline.map(t=>t.done),ratios=baseline.map(t=>100*t.originalDone/t.planned);
    return panel('Predictability across comparable sprints','Five preceding sprints form the baseline; selected Sprint 24 is excluded.',
      table(['Sprint','Original plan completed','Throughput','Cycle median'],trends.map(t=>`<tr><td>${t.sprint}${t.sprint===24?' · selected':''}</td><td>${pct(t.originalDone,t.planned)} (${t.originalDone}/${t.planned})</td><td>${t.done}</td><td>${t.median}d</td></tr>`),'Predictability comparison')+
      `<p class="footnote">Previous throughput median ${median(values)}; observed range ${Math.min(...values)}–${Math.max(...values)}. Previous plan-completion median ${median(ratios).toFixed(1)}%. This small sample describes variation; it is not a forecast or target.</p>`);
  }
  function workMixPanel(){
    return panel('Work mix & quality context','Counts across closing scope; removed items excluded.',
      table(['Issue type','At close','Completed'],['Story','Bug','Task'].map(type=>{const rows=issues.filter(i=>!i.removed&&i.type===type);return `<tr><td>${link(`type-${type}`,type,rows)}</td><td>${rows.length}</td><td>${count(rows,i=>i.done)}</td></tr>`;}),'Work mix')+
      `<p class="footnote">${link('reopened','1 reopened issue',issues.filter(i=>i.reopened))} A Bug type is not an escaped-defect measure. Capacity, dependency ownership, technical-debt classification and post-release quality evidence are not recorded in this fixture.</p>`);
  }
  const configs={
    Team:{title:'Sprint delivery & team contribution',description:'Shared delivery, scope movement and developer assignment context.',focus:'all'},
    Developer:{title:'My sprint contribution & follow-up',description:'Selected developer’s closing assignments, unfinished work and elapsed cycle times.',focus:'person'},
    'PO / BA':{title:'Outcomes, acceptance & scope',description:'Goal-linked delivery, feature progress, acceptance evidence and reasons for scope changes.',focus:'stories'},
    'Scrum Master':{title:'Flow, carryover & improvement',description:'Elapsed cycle times, unfinished queues, repeated carryover and current action follow-up.',focus:'unfinished'},
    'Engineering Manager':{title:'Predictability, work mix & team context',description:'Multi-sprint delivery variation, work composition, quality context and developer assignments.',focus:'all'}
  };
  const prompts={
    Team:['Agree how to finish or remove the remaining review work.','Confirm how the additions affected the shared plan.','Agree the next step for repeated unfinished work.'],
    Developer:['Check the review needs and handoff for your affected tickets.','Clarify acceptance and dependencies for affected additions.','Record the next concrete step on your affected tickets.'],
    'PO / BA':['Confirm acceptance evidence for the reviewed scope.','Record who requested each change and its impact on the sprint goal.','Review the remaining goal-linked scope and whether to split or reprioritize it.'],
    'Scrum Master':['Discuss the review queue and any recorded constraints.','Bring the timing and reasons for changes to the retrospective.','Agree an owner and due date; follow up the next sprint.'],
    'Engineering Manager':['Check whether the queue repeats across comparable sprints before deciding on support.','Compare additions with capacity context; record any missing context.','Review cross-team dependencies and recurring support needs.']
  };
  function render(role,saved,person='Alex'){
    cohorts.clear();
    const config=configs[role]||configs.Team;
    document.getElementById('lens-description').textContent=config.description+' Shared sprint totals stay fixed.';
    document.getElementById('review-person-label').hidden=role!=='Developer';
    const goal=issues.filter(i=>i.goalLinked),stories=issues.filter(i=>i.type==='Story'&&!i.removed),accepted=stories.filter(i=>i.acceptance==='Accepted'),pending=stories.filter(i=>i.done&&i.acceptance!=='Accepted');
    const repeated=unfinished.filter(i=>i.consecutiveCloses>=2),review=unfinished.filter(i=>i.status==='In review');
    let metrics=[],content='';
    if(role==='PO / BA'){
      metrics=[metric('Goal-linked completed',`${count(goal,i=>i.done)} / ${goal.length}`,'Explicit goal-linked sample scope',goal,'goal'),metric('Stories accepted',`${accepted.length} / ${stories.length}`,'Recorded acceptance; retained stories',accepted,'accepted'),metric('Done, acceptance pending',String(pending.length),'Stories awaiting recorded acceptance',pending,'accept-pending'),metric('Changes without reasons',String(count([...added,...removed],i=>!i.scopeReason)),'Of 7 distinct changed issues',issues.filter(i=>(!i.original||i.removed)&&!i.scopeReason),'missing-reason')];
      content=`<div class="review-grid">${deliveryPanel()}${scopePanel()}</div>`+panel('Goal assessment & acceptance','Human assessment remains independent of completion.',`<p class="assessment-copy">${esc(saved.assessment)}${saved.assessmentNote?` · ${esc(saved.assessmentNote)}`:''}</p><button data-assess-goal>Edit goal assessment</button> ${link('goal-open','Unfinished goal-linked work',goal.filter(isOpen))}<p class="footnote">Acceptance fixture: explicit story-level states; no actual demo links attached. Production stores source, author, timestamp and evidence. Requirement-change history is unavailable.</p>`);
    }else if(role==='Scrum Master'){
      metrics=[metric('Cycle time · median',days(median(done.map(i=>i.cycleDays))),'21 completed issues; elapsed calendar time',done,'cycles'),metric('Review queue at close',String(review.length),'Closing review status; no cause inferred',review,'review'),metric('Repeated carryover',String(repeated.length),'Unfinished at two consecutive closes',repeated,'repeated'),metric('Open improvement actions',String(saved.actions.filter(a=>a.status!=='Done').length),'Current browser records; not frozen at close')];
      content=`<div class="review-grid">${flowPanel()}${panel('Retrospective follow-up','Human decisions and current action status.',`<p class="body-note">${saved.actions.filter(a=>a.status==='Done').length} of ${saved.actions.length} locally recorded actions completed.</p><button data-go="retro">Review actions & owners →</button><p class="footnote">Due dates and status are available in Retrospective. Previous-sprint actions are not included in this fixture.</p><h3 class="review-subheading">Coverage before interpretation</h3><p class="body-note">Stage durations are illustrative samples. WIP, blocker intervals and dependency history need normalized Jira events in production.</p>`)}</div>`;
    }else if(role==='Engineering Manager'){
      metrics=[metric('Original-plan completion',pct(count(original,i=>i.done),original.length),'18 / 24 original issues',original,'em-plan'),metric('Throughput vs prior median',`${done.length} vs ${median(trends.slice(0,-1).map(t=>t.done))}`,'Completed issues; preceding 5 sprints'),metric('Gross scope movement',pct(added.length+removed.length,original.length),'7 / 24; distinct additions + final removals',issues.filter(i=>!i.original||i.removed),'em-scope'),metric('Cycle time · P85',days(p85(done.map(i=>i.cycleDays))),'Nearest-rank; 21 completed issues',done,'em-cycle')];
      content=`<div class="review-grid">${trendPanel()}${workMixPanel()}</div>${contributionPanel()}`;
    }else if(role==='Developer'){
      const assigned=issues.filter(i=>i.assignee===person),complete=assigned.filter(i=>i.done),open=assigned.filter(isOpen);
      metrics=[metric('Assigned at close',String(count(assigned,i=>!i.removed)),`${person}; excludes removed work`,assigned.filter(i=>!i.removed),'my-all'),metric('Completed assigned work',String(complete.length),'Closing assignee; shared contribution may differ',complete,'my-done'),metric('Unfinished assigned work',String(open.length),'At close; age stops at sprint close',open,'my-open'),metric('Assigned cycle · median',days(median(complete.map(i=>i.cycleDays))),`${complete.length} completed; full issue elapsed time`,complete,'my-cycle')];
      content=contributionPanel(person)+panel('Follow-up on assigned work','Status, age and repeated carryover for the selected closing assignee.',table(['Issue','At close','Age','Unfinished closes'],open.map(i=>`<tr><td><button class="issue-link" data-issue="${i.key}">${i.key}</button></td><td>${i.status}</td><td>${i.ageDays}d</td><td>${i.consecutiveCloses}</td></tr>`),'Selected developer unfinished work')+(open.length?'':'<p>No unfinished assigned work in this sample.</p>')+`<p class="footnote">Cycle time includes the entire issue lifecycle, including work by other people and waiting. It is not this developer’s working time. Select another developer above to inspect their assignments.</p>`);
    }else{
      metrics=[metric('Added work completed',`${count(added,i=>i.done)} / ${added.length}`,'Separate from original-plan completion',added,'team-added'),metric('Cycle time · median',days(median(done.map(i=>i.cycleDays))),'21 completed; elapsed calendar days',done,'team-cycle'),metric('Repeated carryover',String(repeated.length),'Unfinished at two consecutive closes',repeated,'team-repeat'),metric('Goal-linked unfinished',String(count(goal,isOpen)),'Explicit goal linkage; not a goal assessment',goal.filter(isOpen),'team-goal')];
      content=contributionPanel()+`<div class="review-grid">${scopePanel()}${workMixPanel()}</div>`;
    }
    document.getElementById('role-review').innerHTML=`<div class="section-heading spacious"><div><h2 class="section-title">${config.title}</h2><p>${esc(config.description)}</p></div><span class="badge">${esc(role)} view · Sample data</span></div><div class="surface review-metrics">${metrics.join('')}</div>${content}<details class="review-definitions"><summary>Metric definitions & data limits</summary><p>Counts use the shared 29-issue fixture: 24 original + 5 added; 21 completed + 6 unfinished + 2 removed. All start/entry estimates are 2 points. Cycle median and nearest-rank P85 use completed issues only; unfinished age is separate. Goal links, acceptance and scope reasons are explicit synthetic fields. No AI or external service runs.</p><p>Gross scope movement = (distinct added issues + final removed issues) / original eligible scope. Net growth = (added − removed) / original scope. Event churn, estimate changes, real collaborator credit, capacity and actual released value need separate evidence. Missing values remain unavailable.</p></details>`;
  }
  return {render,configs,getCohort:id=>cohorts.get(id),prompt:(role,id)=>prompts[role]?.[Number(id.slice(-2))-1]||''};
})();
