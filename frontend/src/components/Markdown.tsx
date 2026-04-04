import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate } from 'react-router-dom';
import type { Components } from 'react-markdown';

// Transform wiki-links [[target|label]] before passing to react-markdown
function transformWikiLinks(text: string): string {
  return text.replace(/\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g, (_, target, label) => {
    const slug = target.trim().toLowerCase().replace(/\s+/g, '-');
    return `[${label || target}](/wiki/${slug})`;
  });
}

export function Markdown({ content, className = '' }: { content: string; className?: string }) {
  const navigate = useNavigate();
  const transformed = transformWikiLinks(content);

  const components: Components = {
    a({ href, children }) {
      if (href?.startsWith('/wiki/')) {
        return (
          <span
            className="wiki-link"
            onClick={(e) => { e.preventDefault(); navigate(href); }}
          >
            {children}
          </span>
        );
      }
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
    },
  };

  return (
    <div className={`prose-article ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {transformed}
      </ReactMarkdown>
    </div>
  );
}
