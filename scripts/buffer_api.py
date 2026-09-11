"""Buffer GraphQL transport. Credentials stay in the runner environment."""
import json
import os
import urllib.error
import urllib.request


def graphql(query, variables=None):
    token = os.environ.get('BUFFER_API_KEY', '')
    if not token:
        raise RuntimeError('BUFFER_API_KEY is not configured')
    request = urllib.request.Request(
        'https://api.buffer.com',
        data=json.dumps({'query': query, 'variables': variables or {}}).encode(),
        headers={'Authorization': 'Bearer ' + token,
                 'Content-Type': 'application/json', 'User-Agent': 'Collespo/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Never include request headers or credentials in errors.
        raise RuntimeError(f'Buffer HTTP {exc.code}') from None
    if result.get('errors'):
        messages = '; '.join(e.get('message', 'GraphQL error') for e in result['errors'])
        raise RuntimeError(messages.replace(token, '[redacted]'))
    return result['data']


def inspect_connection():
    organizations = graphql('{ account { organizations { id } } }')['account']['organizations']
    found = []
    for organization in organizations:
        org = json.dumps(organization['id'])
        channels = graphql('{ channels(input: { organizationId: ' + org +
                           ' }) { id name service } }')['channels']
        posts = graphql('{ posts(first: 20, input: { organizationId: ' + org +
                        ' }) { edges { node { id text dueAt channelId status } } } }')['posts']
        found.append({'organizationId': organization['id'], 'channels': channels, 'posts': posts})
    return found


if __name__ == '__main__':
    print(json.dumps(inspect_connection(), ensure_ascii=False, indent=2))
