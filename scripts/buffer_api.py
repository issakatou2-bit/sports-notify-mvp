"""Buffer GraphQL transport. Credentials stay in the runner environment."""
import json
import os
import re
import urllib.error
import urllib.request

MAX_MESSAGE = 200


class BufferReadError(RuntimeError):
    """Where reading Buffer failed, with no credentials or response body.

    `detail()` is safe to print. `str(exc)` keeps the previous short message so
    existing callers such as buffer_daily.py behave the same way.
    """

    def __init__(self, message, *, stage, status=None, messages=(), top_keys=()):
        super().__init__(message)
        self.stage = stage
        self.status = status
        self.messages = tuple(messages)
        self.top_keys = tuple(top_keys)

    def detail(self):
        parts = ['段階=' + self.stage]
        if self.status is not None:
            parts.append('HTTP=' + str(self.status))
        if self.messages:
            parts.append('errors=' + ' | '.join(self.messages)[:MAX_MESSAGE])
        if self.top_keys:
            parts.append('応答の項目=' + ','.join(self.top_keys)[:100])
        return ' '.join(parts)


def _safe(value, token):
    """Return a short message with tokens and token-shaped strings removed."""
    text = str(value)
    if token:
        text = text.replace(token, '[redacted]')
    text = re.sub(r'(?i)(bearer\s+)\S+', r'\1[redacted]', text)
    text = re.sub(r'[A-Za-z0-9_\-]{32,}', '[redacted]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:MAX_MESSAGE]


def graphql(query, variables=None):
    token = os.environ.get('BUFFER_API_KEY', '')
    if not token:
        raise BufferReadError('BUFFER_API_KEY is not configured', stage='送信')
    request = urllib.request.Request(
        'https://api.buffer.com',
        data=json.dumps({'query': query, 'variables': variables or {}}).encode(),
        headers={'Authorization': 'Bearer ' + token,
                 'Content-Type': 'application/json', 'User-Agent': 'Collespo/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = getattr(response, 'status', None)
            try:
                result = json.load(response)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise BufferReadError('Buffer response was not JSON',
                                      stage='JSONの読み込み', status=status) from None
    except urllib.error.HTTPError as exc:
        # Never include request headers or credentials in errors.
        raise BufferReadError(f'Buffer HTTP {exc.code}', stage='送信',
                              status=exc.code) from None
    except BufferReadError:
        raise
    except (urllib.error.URLError, OSError):
        raise BufferReadError('Buffer connection failed', stage='送信') from None
    if not isinstance(result, dict):
        raise BufferReadError('Buffer response was not an object',
                              stage='項目の取り出し')
    top = tuple(sorted(str(key) for key in result)[:10])
    errors = result.get('errors')
    if errors:
        messages = []
        if isinstance(errors, list):
            for error in errors[:5]:
                if isinstance(error, dict):
                    messages.append(_safe(error.get('message', 'GraphQL error'), token))
        summary = '; '.join(messages)[:MAX_MESSAGE] or 'Buffer GraphQL error'
        raise BufferReadError(summary, stage='項目の取り出し', status=status,
                              messages=messages, top_keys=top)
    data = result.get('data')
    if not isinstance(data, dict):
        raise BufferReadError('Buffer response has no data object',
                              stage='項目の取り出し', top_keys=top)
    return data


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
