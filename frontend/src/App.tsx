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

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/wiki" element={<Wiki />} />
          <Route path="/wiki/:slug" element={<ArticleDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/qa" element={<QA />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/ingest" element={<Ingest />} />
          <Route path="/health" element={<Health />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
