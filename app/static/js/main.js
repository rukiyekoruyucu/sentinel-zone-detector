// Dosya yükleme endpoint'i
const UPLOAD_ENDPOINT = '/api/upload';

async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(UPLOAD_ENDPOINT, { method: 'POST', body: formData });
  return res.json();
}

// Tarih formatlama
function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('tr-TR');
}

// Dosya boyutu formatlama
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 ** 2).toFixed(1) + ' MB';
}
