from django.contrib.auth.views import login_required
from django.http import request
import stripe
from django.conf import settings
from django.shortcuts import render, redirect

stripe.api_key = settings.STRIPE_SECRET_KEY

def create_stripe_customer(user):
    customer = stripe.Customer.create(
        email=user.email,
        name=user.get_full_name(),
    )
    return customer

def create_stripe_subscription(customer, price_id):
    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{'price': price_id}],
    )
    return subscription

def cancel_stripe_subscription(subscription_id):
    subscription = stripe.Subscription.retrieve(subscription_id)
    subscription.cancel()
    return subscription

def get_stripe_subscription(subscription_id):
    subscription = stripe.Subscription.retrieve(subscription_id)
    return subscription

def get_stripe_customer(customer_id):
    customer = stripe.Customer.retrieve(customer_id)
    return customer

def get_stripe_invoices(customer_id):
    invoices = stripe.Invoice.list(customer=customer_id)
    return invoices

def get_stripe_invoice(invoice_id):
    invoice = stripe.Invoice.retrieve(invoice_id)
    return invoice

def get_customer_subscriptions(customer_id):
    subscriptions = stripe.Subscription.list(customer=customer_id)
    return subscriptions

def check_customer(user):
    if not hasattr(user, 'owner'):
        return redirect('dashboard_redirect')
    if not user.owner.stripe_customer_id:
        customer = create_stripe_customer(user)
        user.owner.stripe_customer_id = customer.id
        user.owner.save()
    return user.owner.stripe_customer_id

def check_subscription_status(subscription_id):
    subscription = get_stripe_subscription(subscription_id)
    return subscription.status


@login_required
def subscription_status_view(request):
    customer_id = check_customer(request.user)
    subscriptions = get_customer_subscriptions(customer_id)
    
    if not subscriptions.data:
        return render(request, 'callManager/subscription_status.html', {'status': 'No subscription found'})
    if len(subscriptions.data) > 1:
        return render(request, 'callManager/subscription_status.html', {'status': 'Multiple subscriptions found'})
    subscription_id = subscriptions.data[0].id
    status = check_subscription_status(subscription_id)
    return render(request, 'callManager/subscription_status.html', {'status': status})
