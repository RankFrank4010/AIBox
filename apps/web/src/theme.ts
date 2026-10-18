import {
  createDarkTheme,
  createLightTheme,
  type BrandVariants,
  type Theme,
} from '@fluentui/react-components';

export const brandRamp: BrandVariants = {
  10: '#07040F',
  20: '#0D0820',
  30: '#160D3C',
  40: '#21145B',
  50: '#2D1B7B',
  60: '#3A249A',
  70: '#492EBB',
  80: '#5A3CD8',
  90: '#6B4CF0',
  100: '#7F62FF',
  110: '#927BFF',
  120: '#A896FF',
  130: '#C0B4FF',
  140: '#D7D0FF',
  150: '#EAE6FF',
  160: '#F7F5FF',
};

const darkOverrides: Partial<Theme> = {
  colorNeutralBackground1: '#080B12',
  colorNeutralBackground1Hover: '#111725',
  colorNeutralBackground1Pressed: '#151D2E',
  colorNeutralBackground2: '#0C111A',
  colorNeutralBackground2Hover: '#141B2A',
  colorNeutralBackground2Pressed: '#192235',
  colorNeutralBackground3: '#111827',
  colorNeutralBackground3Hover: '#192234',
  colorNeutralBackground3Pressed: '#1D2940',
  colorNeutralBackground4: '#151D2C',
  colorNeutralBackground5: '#1A2436',
  colorNeutralStroke1: '#263247',
  colorNeutralStroke1Hover: '#33435F',
  colorNeutralStroke2: '#1B2536',
  colorNeutralStroke3: '#141C2A',
  colorNeutralStrokeAccessible: '#5F6E89',
  colorNeutralForeground1: '#F3F6FD',
  colorNeutralForeground2: '#B9C3D7',
  colorNeutralForeground2Hover: '#D7DEEE',
  colorNeutralForeground3: '#8694AE',
  colorNeutralForeground4: '#69768E',
  colorNeutralForegroundDisabled: '#556179',
  colorSubtleBackground: 'transparent',
  colorSubtleBackgroundHover: '#131B2A',
  colorSubtleBackgroundPressed: '#182236',
  colorBrandBackground: '#715BFA',
  colorBrandBackgroundHover: '#7F6BFF',
  colorBrandBackgroundPressed: '#604BE2',
  colorBrandForeground1: '#A695FF',
  colorBrandForeground2: '#C0B4FF',
  colorBrandStroke1: '#7D68FF',
  colorCompoundBrandBackground: '#7D68FF',
  colorCompoundBrandBackgroundHover: '#8E7BFF',
  colorCompoundBrandBackgroundPressed: '#6B57E8',
  colorNeutralCardBackground: '#0E1420',
  colorNeutralCardBackgroundHover: '#131B2A',
  fontFamilyBase:
    "'Segoe UI Variable Text', 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans SC', system-ui, sans-serif",
  fontFamilyMonospace:
    "'Cascadia Code', 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
};

const lightOverrides: Partial<Theme> = {
  colorNeutralBackground1: '#F4F6FB',
  colorNeutralBackground1Hover: '#EAEEF8',
  colorNeutralBackground1Pressed: '#DFE5F2',
  colorNeutralBackground2: '#FFFFFF',
  colorNeutralBackground2Hover: '#F2F5FC',
  colorNeutralBackground2Pressed: '#E9EEF9',
  colorNeutralBackground3: '#EDF1F9',
  colorNeutralBackground3Hover: '#E3E9F5',
  colorNeutralBackground4: '#FFFFFF',
  colorNeutralBackground5: '#F2F5FB',
  colorNeutralStroke1: '#D8DFEC',
  colorNeutralStroke1Hover: '#C3CCDE',
  colorNeutralStroke2: '#E4E9F2',
  colorNeutralStroke3: '#EDF1F7',
  colorNeutralStrokeAccessible: '#7A879E',
  colorNeutralForeground1: '#111726',
  colorNeutralForeground2: '#3D4962',
  colorNeutralForeground3: '#65728A',
  colorNeutralForeground4: '#7D899D',
  colorBrandBackground: '#5C48E8',
  colorBrandBackgroundHover: '#6956F5',
  colorBrandBackgroundPressed: '#4B38C9',
  colorBrandForeground1: '#5A45E8',
  colorBrandForeground2: '#4936CF',
  colorBrandStroke1: '#6D5AF2',
  colorCompoundBrandBackground: '#5C48E8',
  colorCompoundBrandBackgroundHover: '#6C59F5',
  colorCompoundBrandBackgroundPressed: '#4B38C9',
  fontFamilyBase:
    "'Segoe UI Variable Text', 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans SC', system-ui, sans-serif",
  fontFamilyMonospace:
    "'Cascadia Code', 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
};

export const aiboxDarkTheme: Theme = { ...createDarkTheme(brandRamp), ...darkOverrides };
export const aiboxLightTheme: Theme = { ...createLightTheme(brandRamp), ...lightOverrides };

export type ThemeMode = 'dark' | 'light' | 'system';

export function resolveTheme(mode: ThemeMode): Theme {
  if (mode === 'light') return aiboxLightTheme;
  if (mode === 'dark') return aiboxDarkTheme;
  const prefersLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
  return prefersLight ? aiboxLightTheme : aiboxDarkTheme;
}

export function resolveThemeName(mode: ThemeMode): 'dark' | 'light' {
  if (mode === 'light') return 'light';
  if (mode === 'dark') return 'dark';
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}
