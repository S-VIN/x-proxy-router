<script lang="ts">
  import type { Tone } from '../../lib/format';

  interface Props {
    tone?: Tone;
    /** Pulses to show that something is in progress. */
    pulse?: boolean;
  }

  let { tone = 'neutral', pulse = false }: Props = $props();
</script>

<span class="dot {tone}" class:pulse aria-hidden="true"></span>

<style>
  .dot {
    display: inline-block;
    flex-shrink: 0;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--color-text-faint);
  }

  .accent {
    background: var(--color-accent);
  }

  .success {
    background: var(--color-success);
  }

  .warning {
    background: var(--color-warning);
  }

  .caution {
    background: var(--color-caution);
  }

  .danger {
    background: var(--color-danger);
  }

  .pulse {
    animation: pulse 1.4s ease-in-out infinite;
  }

  @keyframes pulse {
    50% {
      opacity: 0.35;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .pulse {
      animation: none;
    }
  }
</style>
