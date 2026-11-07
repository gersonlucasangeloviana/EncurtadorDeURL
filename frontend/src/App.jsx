import React, { useEffect, useState } from 'react';
import { createEntry, createLink, deleteEntry, loadCatalog } from './api';

function LinkForm({ projects, paths, busy, onCreate }) {
  const [destination, setDestination] = useState('');
  const [code, setCode] = useState('');
  const [project, setProject] = useState('');
  const [path, setPath] = useState('');

  async function submit(event) {
    event.preventDefault();
    const created = await onCreate({
      destination_url: destination,
      short_code: code || null,
      project_name: project || null,
      public_path: path || null,
    });
    if (created) {
      setDestination('');
      setCode('');
    }
  }

  return (
    <section>
      <h2>Criar link</h2>
      <form onSubmit={submit}>
        <label>
          URL de destino
          <input type="url" placeholder="https://exemplo.com/pagina" value={destination}
            onChange={event => setDestination(event.target.value)} required />
        </label>
        <div className="grid">
          <label>
            Nome personalizado <small>opcional</small>
            <input value={code} onChange={event => setCode(event.target.value)} placeholder="MinhaOferta" />
          </label>
          <label>
            Pasta
            <select value={project} onChange={event => setProject(event.target.value)}>
              <option value="">Sem pasta</option>
              {projects.map(name => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <label>
            Path público
            <select value={path} onChange={event => setPath(event.target.value)}>
              <option value="">Sem path</option>
              {paths.map(name => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        </div>
        <button disabled={busy}>Criar link</button>
      </form>
    </section>
  );
}

function LinkList({ links, busy, onCopy, onDelete }) {
  return (
    <section>
      <h2>Links compartilhados</h2>
      {links.length === 0 && <p>Nenhum link cadastrado ainda.</p>}
      {links.map(link => {
        const expired = link.expires_at && Date.parse(link.expires_at) <= Date.now();
        const status = expired ? 'Expirado' : link.active ? 'Ativo' : 'Pausado';
        return (
          <article key={link.short_code}>
            <div>
              <a href={link.url} target="_blank" rel="noreferrer">{link.url}</a>
              <p className="destination">{link.destination_url}</p>
              <small>{status}{link.project_name && ` · ${link.project_name}`}</small>
            </div>
            <div className="actions">
              <button className="subtle" onClick={() => onCopy(link.url)}>Copiar</button>
              <button className="danger" disabled={busy} onClick={() => onDelete(link.short_code)}>
                Excluir
              </button>
            </div>
          </article>
        );
      })}
    </section>
  );
}

function NamedCollection({ title, inputLabel, placeholder, entries, busy, onCreate, onDelete }) {
  const [name, setName] = useState('');

  async function submit(event) {
    event.preventDefault();
    if (await onCreate(name)) setName('');
  }

  return (
    <section>
      <h2>{title}</h2>
      <form className="inline" onSubmit={submit}>
        <input aria-label={inputLabel} value={name} onChange={event => setName(event.target.value)}
          placeholder={placeholder} required />
        <button disabled={busy}>Adicionar</button>
      </form>
      {entries.map(entry => (
        <p key={entry}>
          {entry}{' '}
          <button className="subtle" disabled={busy} onClick={() => onDelete(entry)}>Excluir</button>
        </p>
      ))}
    </section>
  );
}

function DeleteDialog({ busy, error, onDelete, onCancel }) {
  const [password, setPassword] = useState('');

  async function submit(event) {
    event.preventDefault();
    try {
      await onDelete(password);
    } finally {
      setPassword('');
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <h2 id="delete-title">Confirmar exclusão</h2>
        {error && <div className="error" role="alert">{error}</div>}
        <form onSubmit={submit}>
          <label>
            Senha de administrador
            <input type="password" autoComplete="current-password" value={password}
              onChange={event => setPassword(event.target.value)} autoFocus required />
          </label>
          <div className="actions">
            <button className="danger" disabled={busy}>Excluir</button>
            <button type="button" className="subtle" onClick={onCancel} disabled={busy}>Cancelar</button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function App() {
  const [catalog, setCatalog] = useState({ links: [], projects: [], paths: [] });
  const [error, setError] = useState('');
  const [pendingDelete, setPendingDelete] = useState(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    loadCatalog()
      .then(setCatalog)
      .catch(error => setError(error.message))
      .finally(() => setBusy(false));
  }, []);

  async function mutate(operation, onSuccess) {
    if (busy) return false;
    setBusy(true);
    setError('');
    try {
      await operation();
      onSuccess?.();
      try {
        setCatalog(await loadCatalog());
      } catch {
        setError('Alteração salva, mas não foi possível atualizar as listas. Recarregue a página.');
      }
      return true;
    } catch (error) {
      setError(error.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  function confirmDelete(collection, name) {
    setError('');
    setPendingDelete({ collection, name });
  }

  async function copyLink(url) {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      setError('Não foi possível copiar o link.');
    }
  }

  return (
    <>
      <header><div className="wrap bar"><strong>Encurtador</strong></div></header>
      <main className="wrap">
        <h1>Links mais simples.</h1>
        <p>Crie e organize links. Todos podem visualizar e cadastrar dados. A exclusão exige senha de administrador.</p>
        {error && !pendingDelete && <div className="error" role="alert">{error}</div>}
        <LinkForm projects={catalog.projects} paths={catalog.paths} busy={busy}
          onCreate={link => mutate(() => createLink(link))} />
        <LinkList links={catalog.links} busy={busy} onCopy={copyLink}
          onDelete={code => confirmDelete('links', code)} />
        <div className="grid">
          <NamedCollection title="Pastas" inputLabel="Nova pasta" placeholder="Nome da pasta"
            entries={catalog.projects} busy={busy}
            onCreate={name => mutate(() => createEntry('projects', name))}
            onDelete={name => confirmDelete('projects', name)} />
          <NamedCollection title="Paths públicos" inputLabel="Novo path" placeholder="MinhaEmpresa"
            entries={catalog.paths} busy={busy}
            onCreate={name => mutate(() => createEntry('paths', name))}
            onDelete={name => confirmDelete('paths', name)} />
        </div>
        {pendingDelete && (
          <DeleteDialog busy={busy} error={error} onCancel={() => {
            setError('');
            setPendingDelete(null);
          }} onDelete={password => mutate(
            () => deleteEntry(pendingDelete.collection, pendingDelete.name, password),
            () => setPendingDelete(null),
          )} />
        )}
      </main>
    </>
  );
}
