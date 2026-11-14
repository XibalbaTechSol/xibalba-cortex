import React, { useState } from 'react';
import { Eye, ChevronDown } from 'lucide-react';

interface SpaceSelectorProps {
  currentSpace: string;
  totalMemories: number;
  availableSpaces: string[];
  onSelectSpace: (space: string) => void;
}

export const SpaceSelector: React.FC<SpaceSelectorProps> = ({
  currentSpace,
  totalMemories,
  availableSpaces,
  onSelectSpace,
}) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="absolute top-6 left-6 z-20">
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="cursor-pointer bg-[#0e1013]/90 backdrop-blur-md glow-cyan-border rounded-2xl px-5 py-3 flex items-center gap-3.5 transition-all hover:bg-[#121519] select-none"
      >
        <div className="w-8 h-8 rounded-full bg-cyan-950/60 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
          <Eye className="w-4 h-4" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-white font-medium text-sm">
              {currentSpace === 'all' ? 'All Spaces' : currentSpace}
            </span>
            <ChevronDown className={`w-3.5 h-3.5 text-neutral-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
          </div>
          <p className="text-neutral-400 text-xs">
            {totalMemories} total memories
          </p>
        </div>
      </div>

      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-56 bg-[#111317] border border-[#23272e] rounded-xl shadow-2xl py-2 z-30">
          <button
            onClick={() => {
              onSelectSpace('all');
              setIsOpen(false);
            }}
            className="w-full text-left px-4 py-2 text-sm text-neutral-200 hover:bg-[#1a1d24] flex items-center justify-between"
          >
            <span>All Spaces</span>
            {currentSpace === 'all' && <span className="text-cyan-400 text-xs">✓</span>}
          </button>
          {availableSpaces.map((space) => (
            <button
              key={space}
              onClick={() => {
                onSelectSpace(space);
                setIsOpen(false);
              }}
              className="w-full text-left px-4 py-2 text-sm text-neutral-200 hover:bg-[#1a1d24] flex items-center justify-between"
            >
              <span className="truncate">{space}</span>
              {currentSpace === space && <span className="text-cyan-400 text-xs">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
