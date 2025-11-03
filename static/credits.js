/**
 * Credits monitoring and upgrade prompts
 * Include this file in your chat interface to show credit warnings
 */

let currentCredits = null;
let lowCreditWarningShown = false;

// Check credits on page load
async function checkCredits() {
    try {
        const response = await fetch('/api/usage/stats');
        const data = await response.json();

        currentCredits = data.credits_remaining;
        updateCreditsDisplay(data);

        // Show warnings if needed
        if (currentCredits <= 0) {
            showOutOfCreditsModal();
        } else if (currentCredits <= 5 && !lowCreditWarningShown) {
            showLowCreditsWarning(currentCredits);
            lowCreditWarningShown = true;
        }

        return data;
    } catch (error) {
        console.error('Error checking credits:', error);
        return null;
    }
}

// Update credits display in UI
function updateCreditsDisplay(data) {
    // Update header badge
    const creditsBadge = document.getElementById('credits-badge');
    if (creditsBadge) {
        const color = data.credits_remaining <= 5 ? '#dc3545' : '#cd7c48';
        creditsBadge.innerHTML = `
            <span style="color: ${color}; font-weight: 600;">
                ${data.credits_remaining} credits
            </span>
        `;
    }

    // Update detailed display if exists
    const creditsDetail = document.getElementById('credits-detail');
    if (creditsDetail) {
        const percent = (data.credits_used_this_month / data.tier.monthly_credits) * 100;
        creditsDetail.innerHTML = `
            <div style="margin-bottom: 8px;">
                <strong>${data.credits_remaining}</strong> of ${data.tier.monthly_credits} credits remaining
            </div>
            <div style="width: 100%; height: 6px; background: #e5e5e5; border-radius: 3px; overflow: hidden;">
                <div style="width: ${percent}%; height: 100%; background: linear-gradient(90deg, #cd7c48, #b85c38);"></div>
            </div>
        `;
    }
}

// Show low credits warning (non-blocking)
function showLowCreditsWarning(credits) {
    const warning = document.createElement('div');
    warning.id = 'low-credits-warning';
    warning.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #fff3cd;
        border: 2px solid #ffc107;
        border-radius: 8px;
        padding: 16px 20px;
        max-width: 350px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 9999;
        animation: slideIn 0.3s ease-out;
    `;

    warning.innerHTML = `
        <div style="display: flex; align-items: start; gap: 12px;">
            <span style="font-size: 24px;">⚠️</span>
            <div style="flex: 1;">
                <div style="font-weight: 600; margin-bottom: 4px; color: #856404;">
                    Low Credits Warning
                </div>
                <div style="font-size: 14px; color: #856404; margin-bottom: 12px;">
                    You only have ${credits} credit${credits === 1 ? '' : 's'} remaining.
                    Upgrade your plan to continue using the DevOps Agent.
                </div>
                <div style="display: flex; gap: 8px;">
                    <button onclick="location.href='/billing'"
                            style="padding: 8px 16px; background: #cd7c48; color: white;
                                   border: none; border-radius: 6px; font-weight: 600;
                                   cursor: pointer; font-size: 13px;">
                        Upgrade Now
                    </button>
                    <button onclick="document.getElementById('low-credits-warning').remove()"
                            style="padding: 8px 16px; background: #f0f0f0; color: #666;
                                   border: none; border-radius: 6px; font-weight: 600;
                                   cursor: pointer; font-size: 13px;">
                        Dismiss
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(warning);

    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(400px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);

    // Auto-dismiss after 10 seconds
    setTimeout(() => {
        if (warning.parentNode) {
            warning.remove();
        }
    }, 10000);
}

// Show out of credits modal (blocking)
function showOutOfCreditsModal() {
    // Remove existing modal if any
    const existing = document.getElementById('out-of-credits-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'out-of-credits-modal';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.3s;
    `;

    modal.innerHTML = `
        <div style="background: white; border-radius: 12px; padding: 40px;
                    max-width: 500px; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3);">
            <div style="font-size: 64px; margin-bottom: 20px;">💳</div>
            <h2 style="font-size: 28px; margin-bottom: 12px; color: #2c2d30;">
                Out of Credits
            </h2>
            <p style="font-size: 16px; color: #666; margin-bottom: 30px; line-height: 1.6;">
                You've used all your available credits. Upgrade your plan or purchase
                additional credits to continue using the DevOps Agent.
            </p>

            <div style="display: flex; flex-direction: column; gap: 12px;">
                <button onclick="location.href='/billing'"
                        style="width: 100%; padding: 14px 24px;
                               background: linear-gradient(135deg, #cd7c48, #b85c38);
                               color: white; border: none; border-radius: 8px;
                               font-weight: 600; font-size: 16px; cursor: pointer;
                               transition: transform 0.15s;">
                    View Plans & Pricing
                </button>

                <button onclick="buyCreditsQuick()"
                        style="width: 100%; padding: 14px 24px;
                               background: #f0f0f0; color: #2c2d30;
                               border: none; border-radius: 8px;
                               font-weight: 600; font-size: 16px; cursor: pointer;
                               transition: transform 0.15s;">
                    Buy Credit Pack
                </button>
            </div>

            <div style="margin-top: 20px; font-size: 14px; color: #999;">
                Need help? <a href="/settings" style="color: #cd7c48; text-decoration: none;">Contact Support</a>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Prevent closing by clicking outside
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            // Don't close - user must choose an action
        }
    });
}

// Quick buy credits function
async function buyCreditsQuick() {
    const pack = confirm('Buy 250 credits for $20? (Most popular option)');
    if (!pack) {
        location.href = '/billing';
        return;
    }

    try {
        const response = await fetch('/api/credits/purchase', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pack_size: 250 })
        });

        const data = await response.json();

        if (response.ok) {
            alert('Success! 250 credits added to your account.');
            document.getElementById('out-of-credits-modal')?.remove();
            checkCredits(); // Refresh display
        } else {
            alert('Purchase failed: ' + (data.error || 'Unknown error'));
            location.href = '/billing';
        }
    } catch (error) {
        console.error('Error purchasing credits:', error);
        alert('Error purchasing credits. Redirecting to billing page...');
        location.href = '/billing';
    }
}

// Handle chat response with credit info
function handleChatResponse(response) {
    // Update credits if included in response
    if (response.credits_remaining !== undefined) {
        currentCredits = response.credits_remaining;

        const statsData = {
            credits_remaining: response.credits_remaining,
            credits_used_this_month: response.credits_used_this_month,
            tier: { monthly_credits: response.credits_remaining + response.credits_used_this_month }
        };

        updateCreditsDisplay(statsData);

        // Show warnings
        if (currentCredits <= 0) {
            showOutOfCreditsModal();
        } else if (currentCredits <= 5 && !lowCreditWarningShown) {
            showLowCreditsWarning(currentCredits);
            lowCreditWarningShown = true;
        }
    }
}

// Handle API errors (insufficient credits)
function handleAPIError(error, response) {
    if (response && response.status === 402) {
        // Payment required - out of credits
        showOutOfCreditsModal();
        return true;
    }
    return false;
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    checkCredits();

    // Check credits every 5 minutes
    setInterval(checkCredits, 5 * 60 * 1000);
});

// Export functions for use in other scripts
window.creditsManager = {
    check: checkCredits,
    showWarning: showLowCreditsWarning,
    showModal: showOutOfCreditsModal,
    handleResponse: handleChatResponse,
    handleError: handleAPIError
};
