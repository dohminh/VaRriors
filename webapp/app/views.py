from flask import Blueprint, render_template, request, flash, jsonify, redirect, url_for
from flask_login import login_required, current_user
from . import db
from datetime import datetime, date
from app.models import Cashflow, Budget, SavingGoal, Category
from app.modules.cashflow import net_cash_flow, summarise_month
from sqlalchemy import func
from calendar import monthrange

views = Blueprint('views', __name__)

@views.route('/')
@views.route('/dashboard')
@login_required
def dashboard():
    # Get all cashflows for the current user
    user_cashflows = Cashflow.query.filter_by(user_id=current_user.id).all()
    
    # Calculate totals
    total_income = sum(txn.amount for txn in user_cashflows if txn.kind == 'Income')
    total_expense = sum(txn.amount for txn in user_cashflows if txn.kind == 'Expense')
    total_savings = sum(txn.amount for txn in user_cashflows if txn.kind == 'Savings')
    net_balance = total_income - total_expense - total_savings
    
    # Format the numbers with commas for thousands
    formatted_income = "{:,.0f}".format(total_income)
    formatted_expense = "{:,.0f}".format(total_expense)
    formatted_savings = "{:,.0f}".format(total_savings)
    formatted_balance = "{:,.0f}".format(net_balance)
    
    # Determine if balance is positive or zero
    is_positive = net_balance >= 0
    
    return render_template(
        "dashboard.html", 
        user=current_user, 
        total_income=formatted_income, 
        total_expense=formatted_expense,
        total_savings=formatted_savings,
        net_balance=formatted_balance,
        is_positive=is_positive
    )

@views.route('/add-cashflow', methods=['POST'])
@login_required
def add_cashflow():
    if request.method == 'POST':
        try:
            amount = float(request.form['amount'].replace(',', ''))
            kind = request.form['kind']
            category = request.form.get('category')
            date = datetime.strptime(request.form['date'], "%Y-%m-%d").date()

            new_cashflow = Cashflow(
                                      user_id=current_user.id,
                                      amount=amount,
                                      kind=kind,
                                      category=category,
                                      date=date
                                      )

            db.session.add(new_cashflow)
            db.session.commit()
            flash("Cashflow entry saved successfully!", category="success")
        except Exception as e:
            flash(f"Error saving entry: {str(e)}", category="error")
        
        return redirect(url_for('views.cashflows'))

@views.route('/cashflows')
@login_required
def cashflows():
    # Get the selected month from query parameters, default to 'all' for all transactions
    selected_month = request.args.get('month', 'all')
    
    # Query all cashflows for the user
    user_cashflows = Cashflow.query.filter_by(user_id=current_user.id)
    
    # Filter by selected month only if a specific month is selected
    if selected_month != 'all':
        user_cashflows = user_cashflows.filter(
            db.func.strftime('%Y-%m', Cashflow.date) == selected_month
        )
    
    # Get all months that have cashflows for the dropdown
    months_query = db.session.query(
        db.func.strftime('%Y-%m', Cashflow.date).label('month')
    ).filter_by(user_id=current_user.id).distinct().order_by('month').all()
    
    # Create month options list with 'All Transactions' as first option
    month_options = ['all'] + [m[0] for m in months_query]
    
    # Get the filtered cashflows ordered by date
    user_cashflows = user_cashflows.order_by(Cashflow.date.desc()).all()
    
    return render_template(
        "cashflows.html",
        user=current_user,
        cashflows=user_cashflows,
        month_options=month_options,
        month=selected_month,
        datetime=datetime  # Pass the datetime module to the template
    )

@views.route('/delete-cashflow', methods=['POST'])
@login_required
def delete_cashflow():
    try:
        cashflow_id = request.json['cashflowId']
        cashflow = Cashflow.query.get(cashflow_id)
        if cashflow and cashflow.user_id == current_user.id:
            db.session.delete(cashflow)
            db.session.commit()
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Cashflow not found or unauthorized"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@views.route('/budget', methods=['GET', 'POST'])
@login_required
def budget():
    if request.method == 'POST':
        try:
            # Handle budget updates
            category = request.form.get('category')
            month = request.form.get('month')
            planned_amount = float(request.form.get('planned_amount').replace(',', ''))
            
            # Validate that category is a valid Category enum value
            if category not in [c.value for c in Category]:
                flash('Invalid category selected', 'error')
                return redirect(url_for('views.budget'))
            
            # Check if budget already exists for this category and month
            budget = Budget.query.filter_by(
                user_id=current_user.id,
                category=category,
                month=month
            ).first()
            
            if budget:
                budget.planned_amount = planned_amount
            else:
                budget = Budget(
                    user_id=current_user.id,
                    category=category,
                    month=month,
                    planned_amount=planned_amount
                )
                db.session.add(budget)
            
            db.session.commit()
            flash('Budget updated successfully!', 'success')
            
        except Exception as e:
            flash(f'Error updating budget: {str(e)}', 'error')
    
    # Get current month's budgets and spending
    current_month = datetime.now().strftime('%Y-%m')
    budgets = Budget.query.filter_by(
        user_id=current_user.id,
        month=current_month
    ).all()
    
    # Get all cashflows for the current month
    cashflows = Cashflow.query.filter(
        Cashflow.user_id == current_user.id,
        Cashflow.kind == 'Expense',
        func.strftime('%Y-%m', Cashflow.date) == current_month
    ).all()
    
    # Create a dictionary to store category totals
    category_totals = {category.value: 0 for category in Category}
    for cashflow in cashflows:
        if cashflow.category in category_totals:
            category_totals[cashflow.category] = category_totals[cashflow.category] + float(cashflow.amount)
    
    # Calculate actual spending for each category
    budget_data = []
    total_planned = 0
    total_actual = 0
    alerts = []
    
    # Ensure we have budgets for all categories
    existing_budget_categories = {b.category for b in budgets}
    for category in Category:
        if category.value not in existing_budget_categories and category != Category.OTHER:
            budget_data.append({
                'category': category.value,
                'planned': 0,
                'actual': category_totals[category.value],
                'remaining': -category_totals[category.value],
                'usage_percent': 100 if category_totals[category.value] > 0 else 0
            })
            total_actual += category_totals[category.value]
    
    for budget in budgets:
        actual_spending = category_totals.get(budget.category, 0)
        usage_percent = budget.calculate_usage(actual_spending)
        remaining = budget.get_remaining(actual_spending)
        
        # Generate alerts based on usage
        if usage_percent > 100:
            alerts.append({
                'type': 'danger',
                'message': f'❌ You have exceeded your budget for {budget.category}!'
            })
        elif usage_percent > 90:
            alerts.append({
                'type': 'warning',
                'message': f'⚠ You\'re at {usage_percent:.1f}% of your budget for {budget.category}.'
            })
        
        budget_data.append({
            'category': budget.category,
            'planned': budget.planned_amount,
            'actual': actual_spending,
            'remaining': remaining,
            'usage_percent': usage_percent
        })
        
        total_planned += budget.planned_amount
        total_actual += actual_spending
    
    # Sort budget data by category name
    budget_data.sort(key=lambda x: x['category'])
    
    # Get saving goals
    saving_goals = SavingGoal.query.filter_by(user_id=current_user.id).all()
    goals_data = []
    
    for goal in saving_goals:
        # Calculate current savings from cashflows
        savings_cashflows = Cashflow.query.filter(
            Cashflow.user_id == current_user.id,
            Cashflow.kind == 'Savings',
            Cashflow.date >= goal.start_date,
            Cashflow.date <= goal.target_date
        ).all()
        
        current_savings = sum(float(cf.amount) for cf in savings_cashflows)
        
        # Calculate monthly saving (if goal started in current month)
        if goal.start_date.year == datetime.now().year and goal.start_date.month == datetime.now().month:
            current_monthly_saving = current_savings
        else:
            months_active = ((datetime.now().year - goal.start_date.year) * 12 + 
                           datetime.now().month - goal.start_date.month)
            current_monthly_saving = current_savings / max(1, months_active)
        
        progress = goal.calculate_progress(current_savings)
        
        if progress < 70:
            alerts.append({
                'type': 'warning',
                'message': f'You\'re falling behind on your saving goal: {goal.name}'
            })
        
        goals_data.append({
            'id': goal.id,
            'name': goal.name,
            'total_amount': goal.total_amount,
            'current_savings': current_savings,
            'monthly_required': goal.calculate_monthly_saving(),
            'progress': progress,
            'on_track': goal.is_on_track(current_monthly_saving),
            'start_date': goal.start_date,
            'target_date': goal.target_date,
            'saving_gap': goal.get_saving_gap(current_monthly_saving)
        })
    
    # Check if total budget is exceeded
    if len([d for d in budget_data if d['usage_percent'] > 100]) >= 3:
        alerts.append({
            'type': 'danger',
            'message': 'Spending is drifting from plan in multiple areas.'
        })
    
    return render_template(
        'budget.html',
        user=current_user,
        budget_data=budget_data,
        goals_data=goals_data,
        alerts=alerts,
        total_planned=total_planned,
        total_actual=total_actual,
        current_month=current_month,
        categories=[c.value for c in Category if c != Category.OTHER],  # Pass categories to template
        min=min
    )

@views.route('/add-saving-goal', methods=['POST'])
@login_required
def add_saving_goal():
    try:
        name = request.form.get('name')
        total_amount = float(request.form.get('total_amount').replace(',', ''))
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        target_date = datetime.strptime(request.form.get('target_date'), '%Y-%m-%d').date()
        
        # Make past_savings optional with default 0
        past_savings_str = request.form.get('past_savings', '').strip()
        past_savings = float(past_savings_str.replace(',', '')) if past_savings_str else 0
        
        goal = SavingGoal(
            user_id=current_user.id,
            name=name,
            total_amount=total_amount,
            start_date=start_date,
            target_date=target_date,
            past_savings=past_savings
        )
        
        db.session.add(goal)
        db.session.commit()
        
        flash('Saving goal added successfully!', 'success')
        return jsonify({"success": True})
        
    except Exception as e:
        flash(f'Error adding saving goal: {str(e)}', 'error')
        return jsonify({"success": False, "error": str(e)}), 400
    
    return redirect(url_for('views.budget'))

@views.route('/delete-saving-goal', methods=['POST'])
@login_required
def delete_saving_goal():
    try:
        goal_id = request.json['goalId']
        goal = SavingGoal.query.get(goal_id)
        if goal and goal.user_id == current_user.id:
            db.session.delete(goal)
            db.session.commit()
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Goal not found or unauthorized"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@views.route('/stress-test')
@login_required
def stress_test():
    return render_template("stress_test.html", user=current_user)
