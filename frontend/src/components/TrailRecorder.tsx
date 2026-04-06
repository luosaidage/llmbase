import { useState } from 'react';
import { Icon } from './Icon';
import { useTrail } from '../lib/trail';
import { useLang } from '../lib/lang';

export function TrailRecorder() {
  const { recording, currentTrail, startTrail, stopTrail } = useTrail();
  const { lang } = useLang();
  const zh = lang === 'zh' || lang === 'zh-en';
  const [name, setName] = useState('');
  const [showInput, setShowInput] = useState(false);

  if (recording && currentTrail) {
    return (
      <div className="fixed bottom-6 right-6 bg-primary/90 text-on-primary rounded-xl px-4 py-3 shadow-lg flex items-center gap-3 z-50">
        <div className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
        <div className="text-sm">
          <div className="font-medium">{currentTrail.name}</div>
          <div className="text-xs opacity-80">{currentTrail.steps.length} {zh ? '步' : 'steps'}</div>
        </div>
        <button onClick={stopTrail}
          className="ml-2 px-2 py-1 text-xs bg-on-primary/20 rounded-lg hover:bg-on-primary/30">
          {zh ? '停止' : 'Stop'}
        </button>
      </div>
    );
  }

  if (showInput) {
    return (
      <div className="fixed bottom-6 right-6 bg-surface-container border border-outline-variant/30 rounded-xl px-4 py-3 shadow-lg flex items-center gap-2 z-50">
        <input
          type="text"
          placeholder={zh ? '探索路径名称...' : 'Trail name...'}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { startTrail(name); setShowInput(false); setName(''); } }}
          className="bg-transparent text-sm outline-none w-40 text-on-surface"
          autoFocus
        />
        <button onClick={() => { startTrail(name); setShowInput(false); setName(''); }}
          className="px-2 py-1 text-xs bg-primary text-on-primary rounded-lg">
          {zh ? '开始' : 'Start'}
        </button>
        <button onClick={() => setShowInput(false)}
          className="text-on-surface-variant text-xs">
          <Icon name="close" className="text-[14px]" />
        </button>
      </div>
    );
  }

  return (
    <button onClick={() => setShowInput(true)}
      className="fixed bottom-6 right-6 bg-surface-container border border-outline-variant/30 rounded-full w-12 h-12 flex items-center justify-center shadow-lg hover:border-primary/50 transition-colors z-50"
      title={zh ? '开始探索路径' : 'Start Research Trail'}>
      <Icon name="route" className="text-primary text-[20px]" />
    </button>
  );
}
