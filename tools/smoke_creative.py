"""Optional local-model smoke check in disposable state; never sends or sells."""
import json
from pathlib import Path
import tempfile

from open_service_agents import creative, models
from open_service_agents.storage import Store


def main():
    brief = models.brief(json.loads((Path(__file__).resolve().parents[1] / 'examples/brief.json').read_text()))
    with tempfile.TemporaryDirectory(prefix='osa-outline-smoke-') as folder:
        store = Store(folder)
        task = creative.enqueue(store, 'outlines', {'brief': brief, 'provider': 'ollama'})
        creative.run_one(store)
        result = creative.get(store, task['id'])
        print(json.dumps({'state': result['state'], 'provider': result['provider'],
            'variants': [{'approach': value['approach'], 'characters': len(value['body']), 'citations': value['citations']}
                         for value in result['result'].values()],
            'note': 'Checks generation and schema, not factual accuracy, sales quality or demand.'}), flush=True)


if __name__ == '__main__':
    main()
