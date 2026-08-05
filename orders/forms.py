from django import forms

from .models import OrderItem, Product, Seller


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


class SellerForm(forms.ModelForm):
    """Create or rename a supplier. Admin-only -- employees pick from the list."""

    class Meta:
        model = Seller
        fields = ["name", "phone", "email", "notes"]

    def clean_name(self):
        # The model's unique constraint is case-sensitive; to a shop "Metro" and
        # "metro" are one supplier, so the form is stricter. Excluding self keeps
        # a rename that only changes capitalisation from clashing with itself.
        name = self.cleaned_data["name"].strip()
        clash = Seller.objects.filter(name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"There is already a seller called “{clash.first().name}”.")
        return name


class ProductForm(forms.ModelForm):
    """Lets an employee add a product mid-order when it is missing from the
    catalog. Sellers are chosen from the existing list -- only admins create
    those.
    """

    class Meta:
        model = Product
        fields = ["name", "order_name", "seller", "unit", "unit_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["seller"].queryset = Seller.objects.filter(is_active=True)

    def clean_unit_price(self):
        """Optional, but not zero.

        Blank means "nobody knows yet", which is a real state when a product is
        added mid-order. Zero is a claim that it is free, and would quietly
        understate every total it appears in, so it stays rejected.
        """
        price = self.cleaned_data.get("unit_price")
        if price is None:
            return None
        if price <= 0:
            raise forms.ValidationError("Price must be more than zero, or left empty.")
        return price

    def clean(self):
        cleaned = super().clean()
        name, seller = cleaned.get("name"), cleaned.get("seller")
        # Case-insensitive on purpose: "Oat milk" and "oat milk" from the same
        # seller are the same thing to a shop, even though the database
        # constraint would allow both.
        if name and seller:
            clash = Product.objects.filter(seller=seller, name__iexact=name.strip())
            # Excluding self matters when editing: otherwise saving a product
            # without renaming it would clash with the row being saved.
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError(
                    f"{seller.name} already has a product called “{clash.first().name}”."
                )
        return cleaned
