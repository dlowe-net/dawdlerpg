class DawdleRouter(object):
    def db_for_read(self, model, **hints):
        "Point all operations on dawdle models to 'dawdledb'"
        if model._meta.app_label == 'dawdle':
            return 'game'
        return 'default'

    def db_for_write(self, model, **hints):
        "Point all operations on dawdle models to 'dawdledb'"
        if model._meta.app_label == 'dawdle':
            return 'game'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        "Allow any relation if a both models in dawdle app"
        if obj1._meta.app_label == 'dawdle' and obj2._meta.app_label == 'dawdle':
            return True
        # Allow if neither is dawdle app
        elif 'dawdle' not in [obj1._meta.app_label, obj2._meta.app_label]:
            return True
        return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == 'dawdle':
            return db == 'game'
        return db == 'default'
