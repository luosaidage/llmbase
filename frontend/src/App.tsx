import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { Wiki } from './pages/Wiki';
import { ArticleDetail } from './pages/ArticleDetail';
import { Search } from './pages/Search';
import { QA } from './pages/QA';
import { Graph } from './pages/Graph';
import { Ingest } from './pages/Ingest';
import { Health } from './pages/Health';
import { Explore } from './pages/Explore';
import { Trails } from './pages/Trails';
import { TrailProvider } from './lib/trail';
import { TrailRecorder } from './components/TrailRecorder';

export default function App() {
  return (
    <BrowserRouter>
      <TrailProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/wiki" element={<Wiki />} />
            <Route path="/wiki/:slug" element={<ArticleDetail />} />
            <Route path="/search" element={<Search />} />
            <Route path="/qa" element={<QA />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/explore" element={<Explore />} />
            <Route path="/trails" element={<Trails />} />
            <Route path="/ingest" element={<Ingest />} />
            <Route path="/health" element={<Health />} />
          </Route>
        </Routes>
        <TrailRecorder />
      </TrailProvider>
    </BrowserRouter>
  );
}
