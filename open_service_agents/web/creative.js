// Extends the existing studio; user/model text always goes through textContent.
let creativeTasks=[], creativeSignature='';
titles.creative='Plans & revisions';
const creativeNav=el('button',titles.creative);
creativeNav.dataset.view='creative';
$('#navigation').append(creativeNav);
const creativeView=el('section',undefined,'view');
creativeView.id='view-creative';creativeView.hidden=true;
const creativePanel=el('section',undefined,'panel');
creativePanel.append(el('h2','Choose the direction. Shape the draft.'),
  el('p','Compare three outlines before writing a product. Review AI revisions alongside the original before saving them. Work continues in the background, even after you close this tab.'));
const creativeList=el('div',undefined,'stack');creativeList.id='creative-tasks';
creativePanel.append(creativeList);creativeView.append(creativePanel);$('#workspace').append(creativeView);

const workflowLabel=el('label','How would you like to start?');
const workflow=el('select');workflow.name='workflow';
populateSelect(workflow,[['outlines','Compare three outlines first'],['draft','Generate the full draft directly']]);
workflowLabel.append(workflow);$('#brief-form').prepend(workflowLabel);
$('#brief-form button:not([type])').textContent='Start product';
const contextActions=el('div',undefined,'actions');
contextActions.append(action('Clear additional sources & creators',()=>{extraSources=[];includedLeads=[];contextCount();notice('Additional selections cleared. The primary source remains in the form.');}));
$('#brief-form').append(contextActions);
$('#login').addEventListener('submit',safe(async()=>{await loadCreative();}));
$('#refresh').addEventListener('click',safe(loadCreative));

async function loadCreative(){
  const tasks=await api('/v1/creative');
  const signature=JSON.stringify(tasks);
  creativeTasks=tasks;
  if(signature===creativeSignature)return;
  creativeSignature=signature;creativeList.replaceChildren();
  if(!tasks.length)creativeList.append(el('p','Start a product to compare outlines, or open a completed draft and ask AI to revise a section.','empty'));
  for(const task of tasks){
    const card=el('article',undefined,'card');
    card.append(el('h3',task.payload.brief.topic),el('span',task.kind+' · '+task.state+' · '+task.provider,'tag'));
    if(task.error)card.append(el('p',task.error));
    if(['queued','running'].includes(task.state))card.append(el('p',task.kind==='outlines'?Object.keys(task.result).length+' of 3 outlines saved. Waiting for the generation worker.':'Revision is being prepared. The original section is unchanged.'));
    if(task.state==='failed')card.append(action('Retry from saved progress',async()=>{await api('/v1/creative/retry',{id:task.id});await loadCreative();}));
    if(task.kind==='outlines'){
      const variants=el('div',undefined,'outline-grid');
      for(const [key,a] of Object.entries(task.result)){
        const section=el('section',undefined,'outline-option');
        section.append(el('h4',a.approach),el('strong',a.title));
        const details=el('details');details.append(el('summary','Read outline'),el('pre',a.body),el('small','Sources: '+a.citations.join(', ')));section.append(details);
        if(task.state==='ready')section.append(action('Build this outline',async()=>{
          const job=await api('/v1/creative/select',{id:task.id,variant:key});
          await refresh();await showJob(job.id);view('studio');notice('Selected outline saved. The worker will build the chapters from this plan.');
        }));
        variants.append(section);
      }
      card.append(variants);
    }else{
      card.append(el('p','Section: '+task.payload.stage),el('p','Requested change: '+task.payload.instruction));
      if(task.state==='ready')card.append(action('Compare revision',()=>compareRevision(task)));
      if(task.state==='applied')card.append(el('p','Revision saved to the draft. The previous content is retained in revision history.'));
      card.append(action('Open product',async()=>{await showJob(task.payload.job_id);view('studio');}));
    }
    creativeList.append(card);
  }
}

function requestRevision(job,stage){
  const d=modal('Revise '+stage.replaceAll('_',' ')), f=el('form');
  f.append(el('p','Ask for a clearer explanation, a better exercise, a different tone or stronger sales copy. You will review the replacement before it changes your draft.'),
    field('What should change?','instruction','','textarea'),el('button','Prepare revision'));
  f.elements.instruction.maxLength=2000;
  f.addEventListener('submit',safe(async()=>{
    await api('/v1/creative/revision',{job_id:job.id,stage,provider:job.provider,instruction:f.elements.instruction.value});
    d.close();await loadCreative();view('creative');notice('Revision queued. The original draft is unchanged.');
  }));d.append(f);
}

function compareRevision(task){
  const d=modal('Review proposed revision');d.classList.add('wide-dialog');
  const columns=el('div',undefined,'revision-grid');
  for(const [label,artifact] of [['Original',task.payload.original],['Proposed revision',task.result.suggestion]]){
    const section=el('section');section.append(el('h3',label),el('h4',artifact.title),el('pre',artifact.body),el('small','Sources: '+artifact.citations.join(', ')));columns.append(section);
  }
  d.append(columns,action('Save this revision',async()=>{
    await api('/v1/creative/apply',{id:task.id});d.close();await loadCreative();
    notice('Revision saved. If you edit or approve a draft before applying a suggestion, stale suggestions cannot overwrite it.');
  }));
}

async function showQuality(id){
  const report=await api('/v1/quality/'+id),d=modal('Review chapters & evidence');
  d.append(el('p',report.chapters.length+' / '+report.expected_chapters+' chapters · '+report.total_words.toLocaleString()+' words'),el('p',report.note));
  const chapterTable=el('div',undefined,'table-wrap');
  table(chapterTable,['Chapter','Words','Sources'],report.chapters.map(c=>[c.title,c.words,c.citations.join(', ')]));d.append(chapterTable,el('h3','Items to review'));
  if(!report.findings.length)d.append(el('p','No structural issues found. Editorial and factual review is still needed.'));
  for(const finding of report.findings)d.append(el('p',finding.stage+' · '+finding.message));
  d.append(el('h3','Evidence map'));
  for(const source of report.sources){
    const card=el('section',undefined,'card');card.append(el('h4',source.id+' · '+source.title),sourceLink(source.url),el('p','Usage basis: '+source.rights),el('p','Referenced by: '+(source.chapters.join(', ')||'No chapter')));d.append(card);
  }
}

const templateLabel=el('label','Original page template');
const templateSelect=el('select');templateSelect.name='template_id';
populateSelect(templateSelect,[['field-guide','Practical guide'],['workbook','Hands-on workbook'],['curriculum','Written curriculum']]);
templateLabel.append(templateSelect);
$('#store-form').insertBefore(templateLabel,$('#store-form').children[1]);
templateLabel.append(action('Preview template from product',async()=>{
  const data=await api('/v1/storefronts/template',{product_id:$('#store-product').value,template_id:templateSelect.value});
  const d=modal('Review suggested page copy');
  d.append(el('h3',data.headline),el('p',data.description));
  for(const block of data.blocks)d.append(el('h4',block.heading),el('pre',block.body));
  d.append(el('p','Using this template replaces the unsaved headline, description, sample and sections. Seller details and policies stay in the form.'),
    action('Use this copy in the editor',()=>{
      const f=$('#store-form');for(const key of ['headline','description','sample','template_id'])f.elements[key].value=data[key];
      f.elements.published.checked=false;f.elements.reviewed.checked=false;
      $('#page-blocks').replaceChildren();for(const block of data.blocks)addBlock(block.heading,block.body);
      d.close();notice('Template inserted for editing. Save and publish when ready.');
    }));
}));
const originalPageForm=loadPageForm;
loadPageForm=()=>{originalPageForm();templateSelect.value=storePages.find(p=>p.product_id===$('#store-product').value)?.content.template_id||'field-guide';};
$('#store-product').addEventListener('change',()=>{templateSelect.value=storePages.find(p=>p.product_id===$('#store-product').value)?.content.template_id||'field-guide';});

setInterval(()=>{
  if(token&&!document.hidden&&creativeTasks.some(t=>['queued','running'].includes(t.state)))loadCreative().catch(error=>notice(error.message,true));
},8000);
