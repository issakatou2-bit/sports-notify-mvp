'use strict';
(() => {
  const form = document.getElementById('inquiry-form');
  const draft = document.getElementById('draft');
  const send = document.getElementById('send-mail');
  const sources = new Set(['home', 'about', 'watch', 'youtube', 'bluesky', 'tiktok', 'threads', 'podcast', 'direct']);
  const requested = new URLSearchParams(location.search).get('from');
  const source = sources.has(requested) ? requested : 'direct';
  const id = 'CS-' + (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`).slice(0, 18);
  const subject = `【画像制作の相談】${id}`;
  const updateMail = () => {
    send.href = `mailto:issakatou2@gmail.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(draft.value)}`;
  };
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    draft.value = [
      'コレスポ 画像制作について相談します。', '',
      `チーム名・競技：${document.getElementById('team').value.trim()}`,
      `使いたい日：${document.getElementById('deadline').value.trim() || '未定'}`,
      `相談内容：\n${document.getElementById('brief').value.trim()}`, '',
      '希望プラン：同一デザイン PNG3枚 / 税込3,000円',
      '料金・納期・決済方法・キャンセル条件の確認後に注文を検討します。', '',
      `相談ID：${id}`, `案内元：${source}`,
    ].join('\n');
    updateMail();
    document.getElementById('draft-panel').hidden = false;
    document.getElementById('copy-status').textContent = '';
    draft.focus();
  });
  draft.addEventListener('input', updateMail);
  document.getElementById('copy-draft').addEventListener('click', async () => {
    const status = document.getElementById('copy-status');
    try {
      await navigator.clipboard.writeText(draft.value);
      status.textContent = 'コピーしました。メール本文に貼り付けて送信してください。';
    } catch {
      draft.focus(); draft.select();
      status.textContent = '自動コピーできませんでした。選択された相談文を手動でコピーしてください。';
    }
  });
  form.hidden = false;
})();
