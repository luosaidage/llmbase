import { useState, useEffect, useMemo } from 'react';
import { Icon } from '../components/Icon';
import { ArticleCard } from '../components/ArticleCard';
import { Shimmer } from '../components/Loading';
import { api, type Article } from '../lib/api';

export function Wiki() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [filter, setFilter] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getArticles().then(a => { setArticles(a); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    articles.forEach(a => a.tags?.forEach(t => tags.add(t)));
    return [...tags].sort();
  }, [articles]);

  const filtered = useMemo(() => {
    return articles.filter(a => {
      const matchesFilter = !filter || a.title.toLowerCase().includes(filter.toLowerCase()) || a.summary?.toLowerCase().includes(filter.toLowerCase());
      const matchesTag = !selectedTag || a.tags?.includes(selectedTag);
      return matchesFilter && matchesTag;
    });
  }, [articles, filter, selectedTag]);

  return (
    <div className="p-8 max-w-[1100px] mx-auto">
      <h1 className="font-headline text-3xl font-bold mb-6">Wiki</h1>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="relative flex-1 min-w-[200px]">
          <Icon name="filter_list" className="absolute left-3 top-1/2 -translate-y-1/2 text-outline text-[18px]" />
          <input
            type="text"
            placeholder="Filter articles..."
            className="w-full bg-surface-container border border-outline-variant/40 rounded-lg pl-10 pr-4 py-2 text-sm text-on-surface placeholder:text-outline outline-none focus:border-primary/60"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {allTags.map(tag => (
            <button
              key={tag}
              onClick={() => setSelectedTag(selectedTag === tag ? null : tag)}
              className={`px-3 py-1 rounded-full text-xs transition-colors ${
                selectedTag === tag
                  ? 'bg-primary text-on-primary'
                  : 'bg-surface-high text-on-surface-variant hover:bg-surface-highest'
              }`}
            >
              {tag}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      <p className="text-sm text-on-surface-variant mb-4">{filtered.length} articles</p>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading && Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-surface-container rounded-xl p-5 border border-outline-variant/20">
            <Shimmer lines={3} />
          </div>
        ))}
        {filtered.map(a => <ArticleCard key={a.slug} article={a} />)}
      </div>

      {!loading && filtered.length === 0 && (
        <div className="text-center py-16 text-on-surface-variant">
          <Icon name="search_off" className="text-5xl mb-3 block" />
          <p>No articles match your filter.</p>
        </div>
      )}
    </div>
  );
}
