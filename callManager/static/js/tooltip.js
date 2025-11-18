document.addEventListener('DOMContentLoaded', function () {
    const tooltipTriggers = document.querySelectorAll('[data-tooltip]');
    let currentTooltip = null;
    let mouseX = 0;
    let mouseY = 0;

    // Track mouse position globally
    document.addEventListener('mousemove', function(e) {
        mouseX = e.clientX;
        mouseY = e.clientY;
        
        // Update tooltip position if one is visible
        if (currentTooltip && !currentTooltip.classList.contains('hidden')) {
            positionTooltip(currentTooltip);
        }
    });

    function positionTooltip(tooltip) {
        tooltip.style.position = 'fixed';
        tooltip.style.left = `${mouseX + 10}px`;
        tooltip.style.top = `${mouseY - tooltip.offsetHeight - 10}px`;
        
        // Prevent tooltip from going off-screen
        const rect = tooltip.getBoundingClientRect();
        if (rect.right > window.innerWidth) {
            tooltip.style.left = `${mouseX - tooltip.offsetWidth - 10}px`;
        }
        if (rect.top < 0) {
            tooltip.style.top = `${mouseY + 10}px`;
        }
    }

    tooltipTriggers.forEach(trigger => {
        const tooltip = trigger.parentElement.querySelector('.tooltip');
        const tooltipText = tooltip ? tooltip.querySelector('.tooltip-text') : null;

        // Desktop: Show on hover
        trigger.addEventListener('mouseenter', function () {
            if (tooltip && tooltipText) {
                tooltipText.textContent = trigger.getAttribute('data-tooltip');
                tooltip.classList.remove('hidden');
                currentTooltip = tooltip;
                positionTooltip(tooltip);
            }
        });

        trigger.addEventListener('mouseleave', function () {
            if (tooltip) {
                tooltip.classList.add('hidden');
                currentTooltip = null;
            }
        });

        // Mobile: Toggle on tap/click
        trigger.addEventListener('click', function (e) {
            e.preventDefault();
            if (tooltip && tooltipText) {
                if (tooltip.classList.contains('hidden')) {
                    tooltipText.textContent = trigger.getAttribute('data-tooltip');
                    tooltip.classList.remove('hidden');
                    currentTooltip = tooltip;
                    positionTooltip(tooltip);
                } else {
                    tooltip.classList.add('hidden');
                    currentTooltip = null;
                }
            }
        });
    });

    // Close all tooltips when clicking outside
    document.addEventListener('click', function (e) {
        if (!e.target.closest('[data-tooltip]')) {
            document.querySelectorAll('.tooltip').forEach(tooltip => {
                tooltip.classList.add('hidden');
            });
            currentTooltip = null;
        }
    });
});
