document.addEventListener('DOMContentLoaded', function () {
    const tooltipTriggers = document.querySelectorAll('[data-tooltip]');

    tooltipTriggers.forEach(trigger => {
        const tooltip = trigger.parentElement.querySelector('.tooltip');
        const tooltipText = tooltip ? tooltip.querySelector('.tooltip-text') : null;

        // Desktop: Show on hover
        trigger.addEventListener('mouseenter', function () {
            if (tooltip && tooltipText) {
                tooltipText.textContent = trigger.getAttribute('data-tooltip');
                tooltip.classList.remove('hidden');
                const rect = trigger.getBoundingClientRect();
                tooltip.style.top = `${rect.top - tooltip.offsetHeight - 8}px`;
                tooltip.style.left = `${rect.right + 8}px`;
            }
        });

        trigger.addEventListener('mouseleave', function () {
            if (tooltip) {
                tooltip.classList.add('hidden');
            }
        });

        // Mobile: Toggle on tap/click
        trigger.addEventListener('click', function (e) {
            e.preventDefault();
            if (tooltip && tooltipText) {
                if (tooltip.classList.contains('hidden')) {
                    tooltipText.textContent = trigger.getAttribute('data-tooltip');
                    tooltip.classList.remove('hidden');
                    const rect = trigger.getBoundingClientRect();
                    tooltip.style.top = `${rect.top - tooltip.offsetHeight - 8}px`;
                    tooltip.style.left = `${rect.right + 8}px`;
                } else {
                    tooltip.classList.add('hidden');
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
        }
    });
});
