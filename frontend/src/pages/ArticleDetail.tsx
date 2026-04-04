import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Tag } from '../components/Tag';
import { Markdown } from '../components/Markdown';
import { Loading } from '../components/Loading';
import { Icon } from '../components/Icon';
import { api, type Article } from '../lib/api';

type Lang = 'all' | 'en' | 'zh' | 'ja';

const LANG_LABELS: Record<Lang, string> = {
  all: 'All',
  en: 'English',
  zh: '中文',
  ja: '日本語',
};

function extractLangSection(content: string, lang: Lang): string {
  if (lang === 'all') return content;

  const headers: Record<string, string[]> = {
    en: ['## English'],
    zh: ['## 中文', '## 中文內容'],
    ja: ['## 日本語', '## 日本語の内容'],
  };

  const markers = headers[lang];
  if (!markers) return content;

  for (const marker of markers) {
    const idx = content.indexOf(marker);
    if (idx === -1) continue;

    const start = idx + marker.length;
    // Find the next ## heading (same level)
    const nextH2 = content.indexOf('\n## ', start);
    const section = nextH2 === -1 ? content.slice(start) : content.slice(start, nextH2);
    return section.trim();
  }

  return content; // No sections found, return all
}

function hasMultipleLanguages(content: string): boolean {
  let count = 0;
  if (content.includes('## English')) count++;
  if (content.includes('## 中文')) count++;
  if (content.includes('## 日本語')) count++;
  return count >= 2;
}

export function ArticleDetail() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [article, setArticle] = useState<Article | null>(null);
  const [allArticles, setAllArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [lang, setLang] = useState<Lang>('all');

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setLang('all');
    Promise.all([
      api.getArticle(slug),
      api.getArticles(),
    ]).then(([a, all]) => {
      setArticle(a);
      setAllArticles(all);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [slug]);

  const multilingual = useMemo(() => {
    return article?.content ? hasMultipleLanguages(article.content) : false;
  }, [article?.content]);

  const displayContent = useMemo(() => {
    if (!article?.content) return '';
    return extractLangSection(article.content, lang);
  }, [article?.content, lang]);

  // Extract headings for TOC from displayed content
  const headings = useMemo(() => {
    return [...displayContent.matchAll(/^(#{1,3})\s+(.+)$/gm)].map(m => ({
      level: m[1].length,
      text: m[2],
      id: m[2].toLowerCase().replace(/[^\w]+/g, '-'),
    }));
  }, [displayContent]);

  const related = useMemo(() => {
    if (!article?.tags) return [];
    return allArticles.filter(a =>
      a.slug !== slug && a.tags?.some(t => article.tags.includes(t))
    ).slice(0, 5);
  }, [article, allArticles, slug]);

  if (loading) return <Loading text="Loading article..." />;
  if (!article) return <div className="p-8 text-center text-on-surface-variant">Article not found</div>;

  return (
    <div className="flex">
      {/* Article content */}
      <div className="flex-1 p-8 max-w-[780px] mx-auto">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-on-surface-variant mb-6">
          <span className="cursor-pointer hover:text-primary" onClick={() => navigate('/wiki')}>Wiki</span>
          <span>/</span>
          <span className="text-on-surface">{article.title}</span>
        </div>

        {/* Header */}
        <h1 className="font-headline text-3xl font-bold mb-3">{article.title}</h1>
        {article.summary && (
          <p className="text-on-surface-variant font-body text-lg italic mb-4">{article.summary}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {article.tags?.map(t => <Tag key={t} label={t} />)}
        </div>

        {/* Language switcher */}
        {multilingual && (
          <div className="flex items-center gap-1 mb-6 p-1 bg-surface-high rounded-lg w-fit">
            {(Object.keys(LANG_LABELS) as Lang[]).map(l => (
              <button
                key={l}
                onClick={() => setLang(l)}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  lang === l
                    ? 'bg-primary text-on-primary font-medium'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                {LANG_LABELS[l]}
              </button>
            ))}
          </div>
        )}

        <hr className="border-outline-variant/30 mb-8" />

        {/* Content */}
        <Markdown content={displayContent} />
      </div>

      {/* Right sidebar */}
      <aside className="w-[240px] border-l border-outline-variant/30 p-5 hidden lg:block flex-shrink-0 sticky top-0 h-screen overflow-y-auto">
        {/* Language indicator */}
        {multilingual && (
          <div className="mb-6">
            <h4 className="text-xs uppercase tracking-widest text-on-surface-variant mb-2">Language</h4>
            <div className="flex items-center gap-1.5 text-sm">
              <Icon name="translate" className="text-[16px] text-primary" />
              <span className="text-on-surface-variant">EN / 中 / 日</span>
            </div>
          </div>
        )}

        {/* TOC */}
        {headings.length > 0 && (
          <div className="mb-8">
            <h4 className="text-xs uppercase tracking-widest text-on-surface-variant mb-3">On this page</h4>
            <nav className="space-y-1">
              {headings.map((h, i) => (
                <a
                  key={i}
                  href={`#${h.id}`}
                  className="block text-sm text-on-surface-variant hover:text-primary transition-colors truncate"
                  style={{ paddingLeft: `${(h.level - 1) * 12}px` }}
                >
                  {h.text}
                </a>
              ))}
            </nav>
          </div>
        )}

        {/* Related */}
        {related.length > 0 && (
          <div className="mb-8">
            <h4 className="text-xs uppercase tracking-widest text-on-surface-variant mb-3">Related</h4>
            <div className="space-y-1.5">
              {related.map(a => (
                <div
                  key={a.slug}
                  className="text-sm text-on-surface-variant hover:text-primary cursor-pointer transition-colors truncate"
                  onClick={() => navigate(`/wiki/${a.slug}`)}
                >
                  {a.title}
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
