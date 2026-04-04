import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { ArticleCard } from '../components/ArticleCard';
import { Shimmer } from '../components/Loading';
import { api, type Stats, type Article } from '../lib/api';

export function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);

  useEffect(() => {
    api.getStats().then(setStats).catch(() => {});
    api.getArticles().then(setArticles).catch(() => {});
  }, []);

  const statCards = [
    { icon: 'description', label: 'Raw Documents', value: stats?.raw_count ?? '-', color: 'text-secondary' },
    { icon: 'article', label: 'Wiki Articles', value: stats?.article_count ?? '-', color: 'text-primary' },
    { icon: 'inventory_2', label: 'Filed Outputs', value: stats?.output_count ?? '-', color: 'text-tertiary' },
    { icon: 'analytics', label: 'Total Words', value: stats ? stats.total_words.toLocaleString() : '-', color: 'text-on-surface' },
  ];

  return (
    <div className="p-8 max-w-[1100px] mx-auto">
      <div className="mb-8">
        <h1 className="font-headline text-3xl font-bold mb-1">Curation Overview</h1>
        <p className="text-on-surface-variant font-body italic">Editorial status and intelligence metrics</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
        {statCards.map(s => (
          <div key={s.label} className="bg-surface-container rounded-xl p-5 border border-outline-variant/20">
            <div className="flex items-center gap-2 mb-2">
              <Icon name={s.icon} className={`text-[20px] ${s.color}`} />
              <span className="text-xs text-on-surface-variant uppercase tracking-wider">{s.label}</span>
            </div>
            <div className={`text-3xl font-bold font-label ${s.color}`}>
              {stats ? s.value : <Shimmer lines={1} />}
            </div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="flex gap-3 mb-10">
        <button onClick={() => navigate('/qa')} className="flex items-center gap-2 px-5 py-3 bg-surface-container border border-outline-variant/30 rounded-xl text-sm hover:border-primary/50 transition-colors">
          <Icon name="forum" className="text-primary text-[18px]" /> Ask a Question
        </button>
        <button onClick={() => navigate('/ingest')} className="flex items-center gap-2 px-5 py-3 bg-surface-container border border-outline-variant/30 rounded-xl text-sm hover:border-secondary/50 transition-colors">
          <Icon name="add_link" className="text-secondary text-[18px]" /> Ingest URL
        </button>
        <button onClick={() => navigate('/health')} className="flex items-center gap-2 px-5 py-3 bg-surface-container border border-outline-variant/30 rounded-xl text-sm hover:border-tertiary/50 transition-colors">
          <Icon name="health_and_safety" className="text-tertiary text-[18px]" /> Run Health Check
        </button>
      </div>

      {/* Recent Articles */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-headline text-xl font-semibold">Recent Articles</h2>
        <button onClick={() => navigate('/wiki')} className="text-sm text-primary hover:underline">View all →</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {articles.length === 0 && !stats && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="bg-surface-container rounded-xl p-5 border border-outline-variant/20">
            <Shimmer lines={3} />
          </div>
        ))}
        {articles.slice(0, 6).map(a => <ArticleCard key={a.slug} article={a} />)}
      </div>
      {articles.length === 0 && stats && (
        <div className="text-center py-16 text-on-surface-variant">
          <Icon name="auto_stories" className="text-5xl mb-3 block" />
          <p>No articles yet. Ingest documents and compile them.</p>
        </div>
      )}
    </div>
  );
}
