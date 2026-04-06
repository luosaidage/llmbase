import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { api, type Trail, type TrailStep } from './api';

interface TrailContextType {
  recording: boolean;
  currentTrail: Trail | null;
  startTrail: (name?: string) => void;
  stopTrail: () => void;
  recordStep: (step: Omit<TrailStep, 'ts'>) => void;
}

const TrailContext = createContext<TrailContextType>({
  recording: false,
  currentTrail: null,
  startTrail: () => {},
  stopTrail: () => {},
  recordStep: () => {},
});

export function TrailProvider({ children }: { children: ReactNode }) {
  const [recording, setRecording] = useState(false);
  const [currentTrail, setCurrentTrail] = useState<Trail | null>(null);

  const startTrail = useCallback((name?: string) => {
    api.saveTrailStep(null, { type: 'article', ts: '' }, name || '').then(res => {
      setCurrentTrail(res.trail);
      setRecording(true);
    }).catch(() => {});
  }, []);

  const stopTrail = useCallback(() => {
    setRecording(false);
    setCurrentTrail(null);
  }, []);

  const recordStep = useCallback((step: Omit<TrailStep, 'ts'>) => {
    if (!recording || !currentTrail) return;
    api.saveTrailStep(currentTrail.id, { ...step, ts: '' }).then(res => {
      setCurrentTrail(res.trail);
    }).catch(() => {});
  }, [recording, currentTrail]);

  return (
    <TrailContext.Provider value={{ recording, currentTrail, startTrail, stopTrail, recordStep }}>
      {children}
    </TrailContext.Provider>
  );
}

export const useTrail = () => useContext(TrailContext);
