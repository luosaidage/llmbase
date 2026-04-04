import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import * as d3 from 'd3';
import { Icon } from '../components/Icon';
import { Loading } from '../components/Loading';
import { api, type Article } from '../lib/api';

interface Node extends d3.SimulationNodeDatum { id: string; title: string; tags: string[]; size: number; }
interface Link extends d3.SimulationLinkDatum<Node> { source: string | Node; target: string | Node; }

export function Graph() {
  const navigate = useNavigate();
  const svgRef = useRef<SVGSVGElement>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [showLabels, setShowLabels] = useState(true);

  useEffect(() => {
    api.getArticles().then(a => { setArticles(a); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!svgRef.current || articles.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    // Build nodes & links from wiki-link patterns in summaries/titles
    const nodes: Node[] = articles.map(a => ({
      id: a.slug, title: a.title, tags: a.tags || [], size: 8 + Math.min(a.summary?.length || 0, 200) / 20,
    }));
    const slugSet = new Set(articles.map(a => a.slug));
    const links: Link[] = [];

    // Create links from shared tags
    for (let i = 0; i < articles.length; i++) {
      for (let j = i + 1; j < articles.length; j++) {
        const shared = articles[i].tags?.filter(t => articles[j].tags?.includes(t)) || [];
        if (shared.length > 0) {
          links.push({ source: articles[i].slug, target: articles[j].slug });
        }
      }
    }

    const tagColors: Record<string, string> = {};
    const palette = ['#bdc2ff', '#5de6ff', '#45dfa4', '#ffb4ab', '#cccfff', '#00cbe6'];
    const allTags = [...new Set(articles.flatMap(a => a.tags || []))];
    allTags.forEach((t, i) => { tagColors[t] = palette[i % palette.length]; });

    const g = svg.append('g');

    // Zoom
    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 4])
        .on('zoom', (e) => g.attr('transform', e.transform))
    );

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink<Node, Link>(links).id(d => d.id).distance(80))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => (d as Node).size + 10));

    // Links
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#454652')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.5);

    // Nodes
    const node = g.append('g')
      .selectAll('circle')
      .data(nodes)
      .join('circle')
      .attr('r', d => d.size)
      .attr('fill', d => tagColors[d.tags[0]] || '#8f909e')
      .attr('fill-opacity', 0.8)
      .attr('stroke', '#0c1324')
      .attr('stroke-width', 2)
      .style('cursor', 'pointer')
      .on('click', (_, d) => navigate(`/wiki/${d.id}`))
      .call(d3.drag<SVGCircleElement, Node>()
        .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    // Labels
    const label = g.append('g')
      .selectAll('text')
      .data(nodes)
      .join('text')
      .text(d => d.title)
      .attr('font-size', 11)
      .attr('font-family', 'Inter')
      .attr('fill', '#c5c5d4')
      .attr('text-anchor', 'middle')
      .attr('dy', d => d.size + 14)
      .style('pointer-events', 'none')
      .style('display', showLabels ? 'block' : 'none');

    // Hover effects
    node.on('mouseenter', function(_, d) {
      const connected = new Set<string>();
      links.forEach(l => {
        const s = typeof l.source === 'string' ? l.source : l.source.id;
        const t = typeof l.target === 'string' ? l.target : l.target.id;
        if (s === d.id) connected.add(t);
        if (t === d.id) connected.add(s);
      });
      connected.add(d.id);
      node.attr('fill-opacity', n => connected.has(n.id) ? 1 : 0.15);
      link.attr('stroke-opacity', l => {
        const s = typeof l.source === 'string' ? l.source : (l.source as Node).id;
        const t = typeof l.target === 'string' ? l.target : (l.target as Node).id;
        return s === d.id || t === d.id ? 0.8 : 0.05;
      });
      label.style('opacity', n => connected.has(n.id) ? 1 : 0.1);
    }).on('mouseleave', () => {
      node.attr('fill-opacity', 0.8);
      link.attr('stroke-opacity', 0.5);
      label.style('opacity', 1);
    });

    simulation.on('tick', () => {
      link.attr('x1', d => (d.source as Node).x!).attr('y1', d => (d.source as Node).y!)
          .attr('x2', d => (d.target as Node).x!).attr('y2', d => (d.target as Node).y!);
      node.attr('cx', d => d.x!).attr('cy', d => d.y!);
      label.attr('x', d => d.x!).attr('y', d => d.y!);
    });

    return () => { simulation.stop(); };
  }, [articles, showLabels, navigate]);

  if (loading) return <Loading text="Building graph..." />;

  return (
    <div className="h-full flex flex-col">
      {/* Controls */}
      <div className="flex items-center gap-4 p-4 border-b border-outline-variant/30">
        <h1 className="font-headline text-xl font-bold">Graph Exploration</h1>
        <div className="flex-1" />
        <span className="text-sm text-on-surface-variant">{articles.length} nodes</span>
        <label className="flex items-center gap-2 text-sm text-on-surface-variant cursor-pointer">
          <input type="checkbox" checked={showLabels} onChange={e => setShowLabels(e.target.checked)} className="rounded" />
          Labels
        </label>
      </div>

      {/* Graph */}
      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full" />
        {articles.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant">
            <div className="text-center">
              <Icon name="hub" className="text-5xl mb-3 block" />
              <p>No articles to visualize</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
