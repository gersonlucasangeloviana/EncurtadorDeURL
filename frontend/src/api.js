async function request(path, { method = 'GET', body, password } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (password !== undefined) headers['X-Admin-Password'] = password;

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const { detail } = await response.json().catch(() => ({}));
    const message = typeof detail === 'string' ? detail : detail?.message;
    throw new Error(message || 'Não foi possível concluir a operação.');
  }
  return response.json();
}

export async function loadCatalog() {
  const [links, projects, paths] = await Promise.all([
    request('/links'),
    request('/projects'),
    request('/paths'),
  ]);
  return { links, projects, paths };
}

export function createLink(link) {
  return request('/links', { method: 'POST', body: link });
}

export function createEntry(collection, name) {
  return request(`/${collection}`, { method: 'POST', body: { name } });
}

export function deleteEntry(collection, name, password) {
  const encodedName = encodeURIComponent(name);
  const path = collection === 'projects'
    ? `/projects?name=${encodedName}`
    : `/${collection}/${encodedName}`;
  return request(path, { method: 'DELETE', password });
}
