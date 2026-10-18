import type { DownloadStatus, TranscriptionStatus } from '../api/types';
import type { StatusTone } from '../components/StatusPill';

export function transcriptionTone(status: TranscriptionStatus): StatusTone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'running':
      return 'brand';
    case 'queued':
    case 'cancelling':
      return 'info';
    case 'failed':
      return 'danger';
    case 'cancelled':
    default:
      return 'neutral';
  }
}

export function transcriptionLabel(status: TranscriptionStatus): string {
  switch (status) {
    case 'completed':
      return '已完成';
    case 'running':
      return '转写中';
    case 'queued':
      return '排队中';
    case 'cancelling':
      return '取消中';
    case 'failed':
      return '失败';
    case 'cancelled':
      return '已取消';
    default:
      return status;
  }
}

export function downloadLabel(status: DownloadStatus): string {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'downloading':
      return '下载中';
    case 'cancelling':
      return '取消中';
    case 'completed':
      return '已安装';
    case 'failed':
      return '下载失败';
    case 'cancelled':
      return '已取消';
    default:
      return status;
  }
}

export function downloadTone(status: DownloadStatus): StatusTone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'downloading':
      return 'brand';
    case 'queued':
    case 'cancelling':
      return 'info';
    case 'failed':
      return 'danger';
    default:
      return 'neutral';
  }
}

export function kindLabel(kind: string): string {
  if (kind === 'gpu') return 'GPU';
  if (kind === 'npu') return 'NPU';
  return 'CPU';
}
