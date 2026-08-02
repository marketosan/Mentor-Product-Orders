from django import forms

from .models import OrderItem, Product


class UrgentCheckboxMixin:
    """Shared behaviour for both order-item forms.

    Urgency is a tick box in the UI but low/high on the model. It cannot be
    the model field itself: an unticked box submits nothing at all, which a
    required field would reject as missing. Each form declares its own
    `urgent` field, since Django only collects fields from Form base classes.
    """

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be more than zero.")
        return quantity

    def _apply_urgency(self, item):
        item.urgency = (
            OrderItem.Urgency.HIGH
            if self.cleaned_data.get("urgent")
            else OrderItem.Urgency.LOW
        )
        return item


class AddOrderItemForm(UrgentCheckboxMixin, forms.ModelForm):
    """The quick-add form. The product is chosen through live search, so it
    arrives as a hidden id rather than a dropdown selection.
    """

    urgent = forms.BooleanField(required=False, label="Urgent")

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True, seller__is_active=True),
        widget=forms.HiddenInput,
        error_messages={
            "required": "Search for a product and pick it from the list.",
            "invalid_choice": "That product is no longer available.",
        },
    )

    class Meta:
        model = OrderItem
        fields = ["product", "quantity"]

    def save(self, requested_by, commit=True):
        item = self._apply_urgency(super().save(commit=False))
        item.requested_by = requested_by
        # Freeze the price now so later catalog changes never rewrite history.
        item.unit_price_snapshot = item.product.unit_price
        if commit:
            item.save()
        return item


class EditOrderItemForm(UrgentCheckboxMixin, forms.ModelForm):
    """Only quantity and urgency are editable; swapping product means adding
    a new item instead.
    """

    urgent = forms.BooleanField(required=False, label="Urgent")

    class Meta:
        model = OrderItem
        fields = ["quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["urgent"].initial = self.instance.urgency == OrderItem.Urgency.HIGH

    def save(self, commit=True):
        item = self._apply_urgency(super().save(commit=False))
        if commit:
            item.save()
        return item
