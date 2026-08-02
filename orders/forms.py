from django import forms

from .models import OrderItem, Product


class PositiveQuantityMixin:
    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be more than zero.")
        return quantity


class AddOrderItemForm(PositiveQuantityMixin, forms.ModelForm):
    """The quick-add form. The product is chosen through live search, so it
    arrives as a hidden id rather than a dropdown selection.
    """

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
        fields = ["product", "quantity", "urgency"]

    def save(self, requested_by, commit=True):
        item = super().save(commit=False)
        item.requested_by = requested_by
        # Freeze the price now so later catalog changes never rewrite history.
        item.unit_price_snapshot = item.product.unit_price
        if commit:
            item.save()
        return item


class EditOrderItemForm(PositiveQuantityMixin, forms.ModelForm):
    """Only quantity and urgency are editable; swapping product means adding
    a new item instead.
    """

    class Meta:
        model = OrderItem
        fields = ["quantity", "urgency"]
