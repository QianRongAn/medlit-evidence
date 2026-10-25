/* Spotlight behavior adapted from React Bits SpotlightCard (David Haz).
 * Live JS-CSS registry fetched 2026-10-19. See vendor/ReactBits-LICENSE.md.
 * Vanilla adaptation: local pointer/focus, static light texture, GSAP transforms;
 * no ambient loop, grain, proximity listeners or React runtime.
 */
(() => {
  const gsap = window.gsap;
  if (!gsap) return; // All controls remain usable without the animation library.
  const media = gsap.matchMedia();
  media.add('(prefers-reduced-motion: no-preference)', context => {
    const composer = document.getElementById('searchComposer');
    const light = document.createElement('span');
    light.className = 'composer-light';
    light.setAttribute('aria-hidden', 'true');
    // React Bits' smooth falloff, painted once instead of regenerating per frame.
    const stops = [];
    for (let i = 0; i <= 14; i++) {
      const t = i / 14;
      const smooth = 1 - t * t * (3 - 2 * t);
      const glow = Math.exp(-4.6 * t * t) * (1 - t ** 6);
      stops.push(`rgba(255,255,255,${(smooth + (glow - smooth) * .7).toFixed(3)}) ${t * 100}%`);
    }
    light.style.background = `radial-gradient(circle, ${stops.join(',')})`; // taste-skill-ignore: user-requested React Bits light, input only
    composer.prepend(light);
    const moveX = gsap.quickTo(light, 'x', { duration: .35, ease: 'power2.out' });
    const moveY = gsap.quickTo(light, 'y', { duration: .35, ease: 'power2.out' });
    const fade = gsap.quickTo(light, 'opacity', { duration: .2, overwrite: 'auto' });
    const locate = (x, y) => {
      moveX(x); moveY(y);
      fade(.55);
    };
    const onMove = event => {
      if (event.pointerType === 'touch') return;
      const box = composer.getBoundingClientRect();
      locate(event.clientX - box.left, event.clientY - box.top);
    };
    const onFocus = event => {
      const box = composer.getBoundingClientRect();
      const target = event.target.getBoundingClientRect();
      locate(target.left + target.width / 2 - box.left, target.top + target.height / 2 - box.top);
    };
    const hide = () => fade(0);
    const onBlur = event => { if (!composer.contains(event.relatedTarget)) hide(); };
    composer.addEventListener('pointermove', onMove);
    composer.addEventListener('pointerleave', hide);
    composer.addEventListener('focusin', onFocus);
    composer.addEventListener('focusout', onBlur);

    const onAction = event => context.add(() => {
      const { kind, element } = event.detail;
      if (!element) return;
      gsap.killTweensOf(element);
      if (kind === 'drawer') {
        gsap.fromTo(element, { x: 30, opacity: .6 },
          { x: 0, opacity: 1, duration: .3, ease: 'power2.out', clearProps: 'transform,opacity' });
      } else if (kind === 'source') {
        gsap.fromTo(element, { y: 3 },
          { y: 0, duration: .25, ease: 'power2.out', clearProps: 'transform' });
      } else if (kind === 'abstract' && element.open) {
        const text = element.querySelector('.abstract-full');
        gsap.fromTo(text, { opacity: .4, y: 4 },
          { opacity: 1, y: 0, duration: .22, clearProps: 'transform,opacity' });
      }
    });
    const onToggle = event => {
      if (event.target.matches('.abstract-details')) onAction({ detail: { kind: 'abstract', element: event.target } });
    };
    document.addEventListener('medlit:action', onAction);
    document.addEventListener('toggle', onToggle, true);
    return () => {
      composer.removeEventListener('pointermove', onMove);
      composer.removeEventListener('pointerleave', hide);
      composer.removeEventListener('focusin', onFocus);
      composer.removeEventListener('focusout', onBlur);
      document.removeEventListener('medlit:action', onAction);
      document.removeEventListener('toggle', onToggle, true);
      light.remove();
    };
  });
  window.addEventListener('pagehide', () => media.revert(), { once: true });
})();
