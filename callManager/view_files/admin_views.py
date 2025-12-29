from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from callManager.forms import WorkerForm
from callManager.models import Worker
from django.contrib.auth.views import login_required
from django.shortcuts import render, redirect

@login_required
def admin_view_workers(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('dashboard_redirect')
    workers = Worker.objects.all()
    search_query = request.GET.get('search', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    if search_query or skill_id:
        query = Q()
        if search_query:
            query &= Q(name__icontains=search_query) | Q(phone_number__icontains=search_query)
        if skill_id:
            query &= Q(labor_types__id=skill_id)
        workers = workers.filter(query)
    paginator = Paginator(workers, int(request.GET.get('per_page', manager.per_page_preference)))
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    if request.method == "POST":
        if 'add_worker' in request.POST:
            form = WorkerForm(request.POST, company=manager.company)
            if form.is_valid():
                if Worker.objects.filter(phone_number=form.cleaned_data['phone_number'], company=manager.company).exists():
                    messages.error(request, "Worker with this phone number already exists.")
                    return redirect('view_workers')
                worker = form.save(commit=False)
                if worker.phone_number.startswith('1') and len(worker.phone_number) == 11:
                    worker.phone_number = f"+{worker.phone_number}"
                elif not worker.phone_number.startswith('+') and len(worker.phone_number) == 10:
                    worker.phone_number = f"+1{worker.phone_number}"
                worker.save()
                worker.add_company(manager.company)
                messages.success(request, f"Worker {worker.name} added successfully.")
                query_params = {}
                if page_number != '1':
                    query_params['page'] = page_number
                if search_query:
                    query_params['search'] = search_query
                if skill_id:
                    query_params['skill'] = skill_id
                redirect_url = reverse('view_workers')
                if query_params:
                    redirect_url += '?' + urlencode(query_params)
                return redirect(redirect_url)
            else:
                messages.error(request, "Failed to add worker. Please check the form errors.")
    labor_types = LaborType.objects.filter(company=manager.company)
    context = {
        'workers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'skill_id': skill_id,
        'add_form': form,
        'labor_types': labor_types}
    return render(request, 'callManager/view_workers.html', context)

@login_required
def list_users(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('dashboard_redirect')
    users = User.objects.all().order_by('username')
    paginator = Paginator(users, 25)
    page_number = request.GET.get('page', 1)
    try:
        users = paginator.page(page_number)
    except PageNotAnInteger:
        users = paginator.page(1)
    except EmptyPage:
        users = paginator.page(paginator.num_pages)

    return render(request, 'callManager/list_users.html', {'users': users})

@login_required
def search_users(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('dashboard_redirect')
    users = User.objects.all()
    search_query = request.GET.get('search', '').strip()
    if search_query:
        users = users.filter(Q(username__icontains=search_query) | Q(email__icontains=search_query) | Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query) | Q(manager__company__name__icontains=search_query))
        paginator = Paginator(users, 25)
        print(users)
        page_number = request.GET.get('page', 1)
        try:
            users = paginator.page(page_number)
        except PageNotAnInteger:
            users = paginator.page(1)
        except EmptyPage:
            users = paginator.page(paginator.num_pages)
    return render(request, 'callManager/list_users_partial.html', {'users': users, 'search_query': search_query})
