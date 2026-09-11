"""Small sequential model calls with durable checkpoints instead of a free-form tool loop."""
import json
from .models import artifact
from .providers import provider

STAGES = {
    "opportunity": "Find three concrete product opportunities from supplied evidence. Rank by explicit qualitative criteria, not invented profit probabilities. Select one hypothesis and describe a demand-validation experiment.",
    "creator": "Audit supplied creator content for niche, audience questions, voice and product fit. If no creators are supplied, output a sourcing brief and search queries, not invented people. Respect permission and ownership boundaries.",
    "transformation": "Create a before/after transformation map and a THREE-section outline with measurable reader exercises and acceptance checks. Match the requested format. Course/coaching formats are written curriculum/offer drafts, never pretend videos or sessions exist.",
    "chapter_1": "Write the first practical section of the chosen product: diagnose the reader's problem, explain fundamentals, give a worked example and a worksheet. Cite supplied evidence.",
    "chapter_2": "Write the second practical section: a concrete step-by-step implementation with worked example and an exercise. Continue the selected outline without repeating chapter one.",
    "chapter_3": "Write the final practical section: troubleshooting, a review checklist, a worksheet and next steps. Explain limitations. Do not fabricate specialist expertise.",
    "brand": "Propose an original product name, subtitle, tone and simple color/type direction. Never copy a creator's identity, logo or proprietary branding.",
    "storefront": "Write accurate sales-page copy for the actual drafted deliverable: problem, audience, contents, benefits, limitations, FAQs, a price hypothesis and refund-policy decisions. No fake testimonials or unsupported guarantees.",
    "outreach": "Write two short personalized partnership email variants for each supplied creator, referencing supplied audience evidence. Ask permission to share a sample. No invented relationship. With no creators, provide clearly labeled templates. Include suggested revenue-share discussion terms, not a binding agreement.",
    "launch": "Draft a simple funnel (useful free sample, product page, checkout, delivery) and a ten-story launch sequence. Add a feedback email and test plan tracking actual visits, sales and refunds. No fake urgency or fake social proof."
}


def stages(brief):
    count = brief.get('chapter_count', 3)
    if count == 3:
        return STAGES
    result = {k: STAGES[k] for k in ('opportunity', 'creator')}
    result['transformation'] = STAGES['transformation'].replace('THREE-section', f'{count}-section')
    for i in range(1, count + 1):
        result[f'chapter_{i}'] = f'Write section {i} of {count}, following its position in the selected outline. Include a concrete worked example, an actionable worksheet, and supplied-source citations. Avoid repeating earlier sections. ' + ('Finish with review and limitations.' if i == count else '')
    result.update({k: STAGES[k] for k in ('brand', 'storefront', 'outreach', 'launch')})
    return result


def run_one(store):
    job = store.claim()
    if not job:
        return None
    try:
        model = provider(job["provider"])
        b = json.loads(job["brief"])
        completed = store.job(job["id"])["artifacts"]
        for stage, instruction in stages(b).items():
            if stage in completed:
                continue
            # Keep bounded context; output is checkpointed per stage and reviewed before sale.
            context = {"brief": b, "previous": {k: {"title": v["title"], "body": v["body"][:6000 if k=='transformation' else 500]}
                for k, v in completed.items() if k in ("opportunity", "creator", "transformation")},
                'completed_section_titles': {k:v['title'] for k,v in completed.items() if k.startswith('chapter_')}}
            response = artifact(model.generate(stage, instruction, context), {s["id"] for s in b["sources"]})
            response.update({"provider": model.name, "model": model.model, "stage": stage})
            store.save_artifact(job, stage, response)
            completed[stage] = response
        store.finish(job)
    except Exception as exc:
        # Never persist credential-bearing provider response bodies or full HTTP errors.
        store.finish(job, type(exc).__name__ + ": generation failed; inspect configuration or run a smaller brief")
        raise
    return job["id"]
