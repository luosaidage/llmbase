import { useState, useEffect } from 'react';
import { Icon } from '../components/Icon';
import { Markdown } from '../components/Markdown';
import { api, type RawDoc } from '../lib/api';

export function Ingest() {
  const [url, setUrl] = useState('');
  const [docs, setDocs] = useState<RawDoc[]>([]);
  const [ingesting, setIngesting] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState<{ title: string; content: string; metadata: Record<string, string> } | null>(null);

  useEffect(() => { loadDocs(); }, []);

  async function loadDocs() {
    try { setDocs(await api.getSources()); } catch { /* */ }
  }

  async function handleIngest() {
    if (!url.trim()) return;
    setIngesting(true);
    setMessage('');
    try {
      await api.ingest(url);
      setMessage('Document ingested successfully!');
      setUrl('');
      await loadDocs();
    } catch {
      setMessage('Error: Failed to ingest document.');
    }
    setIngesting(false);
  }

  async function handleCompile() {
    setCompiling(true);
    setMessage('');
    try {
      const res = await api.compile();
      setMessage(`Compiled! ${res.articles_created} new articles created.`);
      await loadDocs();
    } catch {
      setMessage('Error: Compilation failed.');
    }
    setCompiling(false);
  }

  async function viewRaw(slug: string) {
    try {
      const res = await fetch(`/api/sources/${slug}`);
      const data = await res.json();
      if (data.content) setPreview(data);
    } catch { /* */ }
  }

  const uncompiled = docs.filter(d => !d.compiled).length;

  return (
    <div className="p-8 max-w-[900px] mx-auto">
      <h1 className="font-headline text-3xl font-bold mb-6">Ingest Documents</h1>

      {/* URL Ingest */}
      <div className="bg-surface-container rounded-xl p-6 border border-outline-variant/20 mb-6 card-shadow">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Icon name="add_link" className="text-secondary text-[18px]" /> Ingest from URL
        </h3>
        <div className="flex gap-3">
          <input type="text" placeholder="https://example.com/article"
            className="flex-1 bg-surface-high border border-outline-variant/40 rounded-lg px-4 py-2.5 text-sm text-on-surface placeholder:text-outline outline-none focus:border-primary/60"
            value={url} onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleIngest()} />
          <button onClick={handleIngest} disabled={ingesting}
            className="px-5 py-2.5 bg-secondary text-on-secondary rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50">
            {ingesting ? 'Ingesting...' : 'Ingest'}
          </button>
        </div>
      </div>

      {/* Compile Action */}
      {uncompiled > 0 && (
        <div className="bg-primary-container/15 rounded-xl p-5 border border-primary/20 mb-6 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-primary">{uncompiled} uncompiled document{uncompiled > 1 ? 's' : ''}</p>
            <p className="text-xs text-on-surface-variant mt-0.5">Compile them into wiki articles</p>
          </div>
          <button onClick={handleCompile} disabled={compiling}
            className="flex items-center gap-2 px-5 py-2.5 bg-primary text-on-primary rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50">
            <Icon name="auto_awesome" className="text-[16px]" />
            {compiling ? 'Compiling...' : 'Compile All'}
          </button>
        </div>
      )}

      {message && (
        <div className={`rounded-lg px-4 py-3 mb-6 text-sm ${message.startsWith('Error') ? 'bg-error-container/20 text-error' : 'bg-tertiary-container/20 text-tertiary'}`}>
          {message}
        </div>
      )}

      {/* Raw Document Preview Modal */}
      {preview && (
        <div className="fixed inset-0 bg-bg/80 z-50 flex items-center justify-center p-8" onClick={() => setPreview(null)}>
          <div className="bg-surface-container border border-outline-variant/30 rounded-2xl max-w-[700px] w-full max-h-[80vh] overflow-hidden flex flex-col card-shadow-lg"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b border-outline-variant/20">
              <div>
                <h2 className="font-headline font-semibold text-on-surface">{preview.title}</h2>
                <p className="text-xs text-on-surface-variant mt-0.5">
                  {preview.metadata.type} | {preview.metadata.compiled === 'True' ? 'Compiled' : 'Pending'}
                </p>
              </div>
              <button onClick={() => setPreview(null)}
                className="p-2 rounded-lg hover:bg-surface-high text-on-surface-variant">
                <Icon name="close" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              <Markdown content={preview.content} />
            </div>
          </div>
        </div>
      )}

      {/* Documents list */}
      <h2 className="font-headline text-xl font-semibold mb-4">Raw Documents</h2>
      {docs.length === 0 ? (
        <div className="text-center py-12 text-on-surface-variant">
          <Icon name="folder_open" className="text-5xl mb-3 block" />
          <p>No documents ingested yet</p>
        </div>
      ) : (
        <div className="bg-surface-container rounded-xl border border-outline-variant/20 overflow-hidden card-shadow">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-outline-variant/30">
                <th className="text-left px-5 py-3 text-on-surface-variant font-medium">Title</th>
                <th className="text-left px-5 py-3 text-on-surface-variant font-medium">Type</th>
                <th className="text-left px-5 py-3 text-on-surface-variant font-medium">Status</th>
                <th className="text-left px-5 py-3 text-on-surface-variant font-medium">Date</th>
                <th className="text-left px-5 py-3 text-on-surface-variant font-medium w-16"></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d, i) => (
                <tr key={i} className="border-b border-outline-variant/10 last:border-b-0 hover:bg-surface-high/50 transition-colors">
                  <td className="px-5 py-3 text-on-surface">{d.title}</td>
                  <td className="px-5 py-3 text-on-surface-variant">{d.type}</td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${
                      d.compiled ? 'bg-tertiary-container/30 text-tertiary' : 'bg-surface-high text-on-surface-variant'
                    }`}>
                      <Icon name={d.compiled ? 'check_circle' : 'pending'} className="text-[14px]" />
                      {d.compiled ? 'Compiled' : 'Pending'}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-on-surface-variant">{d.ingested_at?.slice(0, 10)}</td>
                  <td className="px-5 py-3">
                    <button onClick={() => viewRaw(d.path.includes('/raw/') ? d.path.split('/raw/')[1] : d.path || d.title)}
                      className="p-1.5 rounded-lg hover:bg-surface-highest text-on-surface-variant hover:text-primary transition-colors"
                      title="Preview raw document">
                      <Icon name="visibility" className="text-[16px]" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
