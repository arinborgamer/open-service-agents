// Run against tests/qa_server.py only. All data is fictional; no outbound accounts.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.OSA_QA_BROWSER?{channel:process.env.OSA_QA_BROWSER}:{})});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1080}});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const base='http://127.0.0.1:8788';
    const token='ui-test-only-token-not-a-secret-0000000000';
    const call=async(route,data)=>{
      const response=await page.request.fetch(base+route,{method:data?'POST':'GET',headers:{Authorization:'Bearer '+token},data});
      assert(response.ok(),route+' '+await response.text());return response.json();
    };
    await page.goto(base+'/studio');
    await page.getByLabel('Operator token').fill(token);
    await page.getByRole('button',{name:'Unlock',exact:true}).click();
    await page.locator('#workspace').waitFor({state:'visible'});
    const form=page.locator('#brief-form');
    await form.locator('[name=topic]').fill('UI verification guide');
    await form.locator('[name=audience]').fill('Fictional readers');
    await form.locator('[name=problem]').fill('Need a repeatable checklist');
    await form.locator('[name=provider]').selectOption('demo');
    await form.locator('[name=chapter_count]').fill('3');
    await form.locator('[name=source_title]').fill('Original fixture notes');
    await form.locator('[name=source_url]').fill('https://example.com/notes');
    await form.locator('[name=source_text]').fill('Start with a specific goal. Try a small change. Review the result. These are fictional notes for software testing.');
    await form.getByRole('button',{name:'Start product',exact:true}).click();
    await page.locator('#view-creative').waitFor({state:'visible'});
    const build=page.getByRole('button',{name:'Build this outline',exact:true}).first();
    await build.waitFor({state:'visible',timeout:25000});
    assert.equal(await page.getByRole('button',{name:'Build this outline',exact:true}).count(),3);
    await page.locator('.outline-option').first().getByText('Read outline',{exact:true}).click();
    fs.mkdirSync(path.resolve('.local/qa'),{recursive:true});
    await page.screenshot({path:path.resolve('.local/qa/outlines-desktop.png'),fullPage:true});
    await build.click();
    await page.locator('#view-studio').waitFor({state:'visible'});
    let generated;
    for(let i=0;i<30;i++){
      const jobs=await call('/v1/jobs');
      const candidate=jobs.find(j=>j.state==='ready'&&j.id!==jobs[jobs.length-1].id);
      if(candidate){
        for(const job of jobs.filter(j=>j.state==='ready')){
          const full=await call('/v1/jobs/'+job.id);
          if(full.brief.topic==='UI verification guide'){generated=full;break;}
        }
      }
      if(generated)break;
      await new Promise(resolve=>setTimeout(resolve,300));
    }
    assert(generated,'Selected outline produced a complete draft');
    await page.getByRole('button',{name:'Refresh',exact:true}).click();
    await page.locator('#jobs .job').filter({hasText:generated.id}).click();
    await page.getByRole('button',{name:'Review quality & sources',exact:true}).click();
    await page.getByRole('heading',{name:'Evidence map',exact:true}).waitFor();
    await page.getByRole('button',{name:'Close',exact:true}).click();
    const chapter=page.locator('#job-detail details').filter({has:page.locator('summary').filter({hasText:'chapter 1'})}).first();
    await chapter.locator('summary').click();
    await chapter.getByRole('button',{name:'Ask AI to revise',exact:true}).click();
    await page.getByLabel('What should change?').fill('Add a clear review exercise.');
    await page.getByRole('button',{name:'Prepare revision',exact:true}).click();
    await page.getByRole('button',{name:'Compare revision',exact:true}).waitFor({timeout:25000});
    await page.getByRole('button',{name:'Compare revision',exact:true}).click();
    await page.getByRole('heading',{name:'Proposed revision',exact:true}).waitFor();
    await page.screenshot({path:path.resolve('.local/qa/revision-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:'Save this revision',exact:true}).click();
    await page.getByText('Revision saved to the draft.',{exact:false}).waitFor();
    const updated=await call('/v1/jobs/'+generated.id);
    assert(updated.artifacts.chapter_1.body.startsWith('DEMO REVISION'));
    await page.getByRole('button',{name:'Store & orders',exact:true}).click();
    await page.getByRole('button',{name:'Preview template from product',exact:true}).click();
    await page.getByRole('button',{name:'Use this copy in the editor',exact:true}).click();
    assert(await page.locator('#store-form [name=headline]').inputValue());
    assert.equal(await page.locator('#page-blocks .editor-block').count(),4);
    assert.equal(await page.locator('#store-form [name=published]').isChecked(),false);
    await page.getByRole('button',{name:'Plans & revisions',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile has no horizontal overflow');
    await page.screenshot({path:path.resolve('.local/qa/outlines-mobile.png'),fullPage:true});
    const pdf=await page.request.get(base+'/v1/pdf/'+generated.id,{headers:{Authorization:'Bearer '+token}});
    assert(pdf.ok());assert.equal(pdf.headers()['content-type'],'application/pdf');
    fs.writeFileSync(path.resolve('.local/qa/product.pdf'),await pdf.body());
    for(const route of ['/v1/creative','/v1/quality/'+generated.id,'/v1/pdf/'+generated.id]){
      assert.equal((await page.request.get(base+route)).status(),401);
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,checks:['outline choices','selected plan generation','quality report','revision preview and apply','template draft','mobile width','PDF download','authentication','no browser errors'],artifacts:'.local/qa'}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
