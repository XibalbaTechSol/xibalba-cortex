import React from 'react';
import {
  Gauge,
  Brain,
  Infinity as InfinityIcon,
  Network,
  Key,
  CreditCard,
  LogOut,
} from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  onSelectTab: (tab: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onSelectTab }) => {
  const mainNav = [
    { id: 'dashboard', label: 'Dashboard', icon: Gauge },
    { id: 'memory', label: 'Memory', icon: Brain },
    { id: 'infinite-chat', label: 'Infinite Chat', icon: InfinityIcon },
    { id: 'memory-graph', label: 'Memory Graph', icon: Network },
  ];

  const bottomNav = [
    { id: 'api-keys', label: 'API Keys', icon: Key },
    { id: 'billing', label: 'Billing', icon: CreditCard },
    { id: 'logout', label: 'Log out', icon: LogOut },
  ];

  return (
    <aside className="w-56 h-screen bg-[#0c0d0e] border-r border-[#191b1e] flex flex-col justify-between py-5 px-3 z-30 select-none">
      <div>
        {/* Brand Logo matching supermemory™ */}
        <div className="flex items-center gap-2.5 px-3 mb-7">
          <svg
            className="w-5 h-5 text-white"
            viewBox="0 0 24 24"
            fill="currentColor"
          >
            {/* 4-point stylized clover / asterisk */}
            <path d="M12 2C12.5 7 17 11.5 22 12C17 12.5 12.5 17 12 22C11.5 17 7 12.5 2 12C7 11.5 11.5 7 12 2Z" />
          </svg>
          <span className="text-white font-medium text-base tracking-tight flex items-center">
            supermemory<span className="text-[10px] ml-0.5 align-super text-neutral-400">™</span>
          </span>
        </div>

        {/* Primary Navigation */}
        <nav className="space-y-1">
          {mainNav.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'text-white bg-[#181a1d]'
                    : 'text-neutral-400 hover:text-neutral-200 hover:bg-[#141618]'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-white' : 'text-neutral-400'}`} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Navigation */}
      <div className="space-y-1 pt-4 border-t border-[#191b1e]">
        {bottomNav.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-neutral-400 hover:text-neutral-200 hover:bg-[#141618] transition-colors"
            >
              <Icon className="w-4 h-4 text-neutral-400" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
};
