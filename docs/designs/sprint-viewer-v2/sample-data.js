/* Synthetic fixture. No network requests, credentials or production issue data. */
window.SprintSample = (() => {
  const titles = ['Idempotency keys','Retry request contract','Payment attempt tracing','Retry backoff policy','Duplicate request tests','Retry response mapping','Payment error categories','Retry dashboard counters','Payment timeout handling','Retry event schema','Payment status endpoint','Retry webhook handling','Retry budget configuration','Payment attempt storage','Retry alert thresholds','Support tracing guide','Payment replay tests','Retry rollout checklist','Retry audit logging','Failure review dashboard','Webhook review coverage','Retry recovery tests','Legacy retry migration','Retry report scheduling','Timeout diagnostics','Retry alert correction','Payment trace cleanup','Gateway recovery check','Retry support runbook'];
  const doneDays = [3,4,4,5,6,4,7,5,3,6,5,4,8,5,6,4,7,5,2,3,2];
  let completedIndex = 0;
  const issues = titles.map((summary, index) => {
    const n=index+201, original=index<24, removed=n===223||n===224;
    const done=n<=218||(n>=225&&n<=227);
    const status=removed?'Removed':done?'Done':[219,220,221,229].includes(n)?'In review':n===228?'Blocked':'In testing';
    const days=done?doneDays[completedIndex++]:null;
    const addedAt=original?'2026-08-17':n>=228?'2026-08-27':'2026-08-24';
    return {key:`PAY-${n}`,summary,type:n>=225?'Bug':index%6===4?'Task':'Story',assignee:[219,201,221,225].includes(n)?'Alex':['Alex','Priya','Sam'][index%3],original,removed,done,status,points:2,addedAt,consecutiveCloses:[219,222].includes(n)?2:1,cycleDays:days,activeDays:days?days*.6:null,reviewDays:days?days*.25:null,testDays:days?days*.15:null,ageDays:done||removed?null:({219:15,220:8,221:6,222:14,228:1,229:1}[n]),reopened:n===212,epic:'Safe payment retries'};
  });
  // Explicit synthetic review metadata. No acceptance, goal link or reason is inferred by the UI.
  issues.forEach((i,index)=>{
    i.epic=index<10?'Safe retries':index<20?'Observability':'Rollout & support';
    i.goalLinked=index<10||[219,222].includes(Number(i.key.slice(4)));
    i.acceptance=i.type!=='Story'?null:i.done?(index<15?'Accepted':'Pending review'):'Not ready';
    i.scopeReason=({'PAY-223':'Deferred by PO','PAY-224':'Dependency unavailable','PAY-225':'Incident follow-up','PAY-227':'Validation defect','PAY-228':'Gateway recovery request'})[i.key]||null;
  });
  const rules=[
    {id:'SV-01',category:'Review queue',keys:issues.filter(i=>i.status==='In review').map(i=>i.key),title:n=>`${n} issues were awaiting review at sprint close`,short:n=>`${n} issues awaiting review`,next:'Review these items together and record any shared constraint.',why:'Closing status maps to Review and the issue is unfinished. Threshold: at least 1 issue. Evaluated at 28 Aug 2026, 18:00 Asia/Kolkata. 29 / 29 issues checked; 4 matched.',action:'Review the closing review queue and record a next step'},
    {id:'SV-02',category:'Scope changes',keys:issues.filter(i=>!i.original&&i.addedAt>='2026-08-27').map(i=>i.key),title:n=>`${n} issues were added in the final 2 working days`,short:n=>`${n} late scope additions`,next:'Check the recorded reason for each late addition.',why:'First sprint entry is on 27 or 28 Aug 2026. Sample calendar: Monday–Friday, no holidays. Threshold: at least 1 issue. All 5 added issue entry dates are available; 2 matched.',action:'Review the reasons for late scope additions'},
    {id:'SV-03',category:'Carryover',keys:issues.filter(i=>!i.done&&!i.removed&&i.consecutiveCloses>=2).map(i=>i.key),title:n=>`${n} issues remained unfinished across 2 sprint closes`,short:n=>`${n} issues carried across sprints`,next:'Discuss whether these items need slicing, clarification or dependency follow-up.',why:'Issue remained in closing scope and unfinished at Sprint 23 and Sprint 24 close. Threshold: 2 consecutive closes on this board. Sample boundary coverage is complete; 2 matched.',action:'Agree next steps for repeated unfinished work'}
  ];
  const trends=[{sprint:19,planned:23,originalDone:18,done:20,added:4,removed:1,median:5.2},{sprint:20,planned:25,originalDone:20,done:23,added:4,removed:2,median:4.8},{sprint:21,planned:22,originalDone:17,done:19,added:3,removed:1,median:5.5},{sprint:22,planned:24,originalDone:19,done:22,added:4,removed:2,median:4.6},{sprint:23,planned:26,originalDone:18,done:20,added:3,removed:2,median:5.4},{sprint:24,planned:24,originalDone:18,done:21,added:5,removed:2,median:5}];
  return {issues,rules,trends};
})();
