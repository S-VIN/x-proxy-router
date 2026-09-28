<script lang="ts">
  interface Props {
    size?: number;
    /** Announced to screen readers; omit when the surrounding text already says it. */
    label?: string;
  }

  let { size = 16, label }: Props = $props();
</script>

<svg
  class="spinner"
  width={size}
  height={size}
  viewBox="0 0 16 16"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
>
  <circle
    cx="8"
    cy="8"
    r="6"
    fill="none"
    stroke="currentColor"
    stroke-opacity="0.2"
    stroke-width="2"
  />
  <path
    d="M14 8a6 6 0 0 0-6-6"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
  />
</svg>

<style>
  .spinner {
    display: block;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation-duration: 2.4s;
    }
  }
</style>
