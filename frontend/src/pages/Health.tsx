import { useState, useEffect } from 'react';
import { Icon } from '../components/Icon';
import { Markdown } from '../components/Markdown';
import { Shimmer } from '../components/Loading';
import { api, type LintResults } from '../lib/api';

export function Health() {
  const [results, setResults] = useState<LintResults | null>(null);
  const [deepReport, setDeepReport] = useState('');
  const [loadingBasic, setLoadingBasic] = useState(false);
  const [loadingDeep, setLoadingDeep] = useState(false);

  async function runBasic() {
    setLoadingBasic(true);
    try {
      const res = await api.lint(false);
      if (res.results) setResults(res.results);
    } catch { /* */ }
    setLoadingBasic(false);
  }

  async function runDeep() {
    setLoadingDeep(true);
    try {
      const res = await api.lint(true);
      if (res.report) setDeepReport(res.report);
    } catch { /* */ }
    setLoadingDeep(false);
  }

  const categories = results ? [
    { label: 'Structural', icon: 'architecture', issues: results.structural, color: 'text-primary' },
    { label: 'Broken Links', icon: 'link_off', issues: results.broken_links, color: 'text-error' },
    { label: 'Orphan Articles', icon: 'visibility_off', issues: results.orphans, color: 'text-secondary' },
    { label: 'Missing Metadata', icon: 'label_off', issues: results.missing_metadata, color: 'text-on-surface-variant' },
  ] : [];

  return (
    <div className="p-8 max-w-[900px] mx-auto">
      <h1 className="font-headline text-3xl font-bold mb-6">Wiki Health</h1>

      {/* Actions */}
      <div className="flex gap-3 mb-8">
        <button
          onClick={runBasic}
          disabled={loadingBasic}
          className="flex items-center gap-2 px-5 py-3 bg-surface-container border border-outline-variant/30 rounded-xl text-sm hover:border-primary/50 transition-colors disabled:opacity-50"
        >
          <Icon name="health_and_safety" className="text-tertiary text-[18px]" />
          {loadingBasic ? 'Checking...' : 'Run Health Check'}
        </button>
        <button
          onClick={runDeep}
          disabled={loadingDeep}
          className="flex items-center gap-2 px-5 py-3 bg-surface-container border border-outline-variant/30 rounded-xl text-sm hover:border-secondary/50 transition-colors disabled:opacity-50"
        >
          <Icon name="psychology" className="text-secondary text-[18px]" />
          {loadingDeep ? 'Analyzing...' : 'Deep Analysis (LLM)'}
        </button>
      </div>

      {/* Overview cards */}
      {results && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {categories.map(c => (
              <div key={c.label} className="bg-surface-container rounded-xl p-4 border border-outline-variant/20 text-center">
                <Icon name={c.icon} className={`text-2xl ${c.color} mb-1`} />
                <div className="text-2xl font-bold">{c.issues.length}</div>
                <div className="text-xs text-on-surface-variant">{c.label}</div>
              </div>
            ))}
          </div>

          {/* Overall */}
          <div className={`rounded-xl px-5 py-4 mb-8 flex items-center gap-3 ${
            results.total_issues === 0
              ? 'bg-tertiary-container/20 border border-tertiary/20'
              : 'bg-surface-container border border-outline-variant/20'
          }`}>
            <Icon
              name={results.total_issues === 0 ? 'check_circle' : 'warning'}
              className={`text-2xl ${results.total_issues === 0 ? 'text-tertiary' : 'text-error'}`}
            />
            <span className="text-sm">
              {results.total_issues === 0
                ? 'All checks passed! Wiki is healthy.'
                : `${results.total_issues} issue${results.total_issues > 1 ? 's' : ''} found`
              }
            </span>
          </div>

          {/* Issue details */}
          {categories.filter(c => c.issues.length > 0).map(c => (
            <div key={c.label} className="mb-6">
              <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                <Icon name={c.icon} className={`text-[16px] ${c.color}`} />
                {c.label} ({c.issues.length})
              </h3>
              <div className="bg-surface-container rounded-xl border border-outline-variant/20 divide-y divide-outline-variant/10">
                {c.issues.map((issue, i) => (
                  <div key={i} className="px-5 py-3 text-sm text-on-surface-variant">{issue}</div>
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {loadingBasic && <Shimmer lines={4} />}

      {/* Deep report */}
      {loadingDeep && (
        <div className="bg-surface-container rounded-xl p-6 border border-outline-variant/20 mt-6">
          <Shimmer lines={8} />
        </div>
      )}

      {deepReport && !loadingDeep && (
        <div className="mt-6">
          <h2 className="font-headline text-xl font-semibold mb-3 flex items-center gap-2">
            <Icon name="psychology" className="text-secondary" /> Deep Analysis
          </h2>
          <div className="bg-surface-container rounded-xl p-6 border border-outline-variant/20">
            <Markdown content={deepReport} />
          </div>
        </div>
      )}

      {!results && !loadingBasic && !deepReport && !loadingDeep && (
        <div className="text-center py-16 text-on-surface-variant">
          <Icon name="health_and_safety" className="text-5xl mb-3 block" />
          <p>Run a health check to see wiki status</p>
        </div>
      )}
    </div>
  );
}
