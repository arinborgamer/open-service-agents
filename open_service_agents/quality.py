"""Explainable editorial diagnostics. These checks cannot certify factual accuracy."""
import re


def report(job):
    artifacts = job['artifacts']
    count = job['brief'].get('chapter_count', 3)
    chapters, findings = [], []
    source_use = {s['id']: [] for s in job['brief']['sources']}
    seen = {}
    if job['state'] != 'ready':
        findings.append({'level': 'attention', 'stage': 'product', 'message': 'Generation is not complete.'})
    if job['provider'] == 'demo':
        findings.append({'level': 'attention', 'stage': 'product', 'message': 'Demonstration fixture. This edition cannot be sold through checkout.'})
    for i in range(1, count + 1):
        stage = f'chapter_{i}'
        a = artifacts.get(stage)
        if not a:
            findings.append({'level': 'attention', 'stage': stage, 'message': 'Chapter is missing.'})
            continue
        words = len(re.findall(r'\b\w+\b', a['body']))
        chapters.append({'stage': stage, 'title': a['title'], 'words': words, 'citations': a['citations']})
        if words < 250:
            findings.append({'level': 'review', 'stage': stage, 'message': f'Short section ({words} words). Check whether the exercise and worked example are usable.'})
        normalized = re.sub(r'\W+', ' ', a['body']).lower().strip()
        if normalized in seen:
            findings.append({'level': 'attention', 'stage': stage, 'message': f'Body repeats {seen[normalized]} exactly apart from punctuation. Replace duplicate material.'})
        seen[normalized] = stage
        for source in a['citations']:
            if source in source_use:
                source_use[source].append(stage)
            else:
                findings.append({'level': 'attention', 'stage': stage, 'message': f'Unknown citation: {source}.'})
        if re.search(r'\[(?:insert|todo|tbd|creator|your\b)[^\]]*\]|\b(?:TODO|TBD)\b', a['body'], re.I):
            findings.append({'level': 'attention', 'stage': stage, 'message': 'Possible unfinished placeholder. Review before publishing.'})
    sources = [{'id': s['id'], 'title': s['title'], 'url': s['url'], 'rights': s['rights'], 'chapters': source_use[s['id']]}
               for s in job['brief']['sources']]
    return {'job_id': job['id'], 'chapters': chapters, 'total_words': sum(c['words'] for c in chapters),
            'expected_chapters': count, 'findings': findings, 'sources': sources,
            'note': 'Structural checks only. Citation presence is not proof that a claim is supported; word count is not a quality score. Review evidence, rights and reader outcomes yourself.'}
