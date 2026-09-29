env 'CI' do
  gem 'ci-only'
  env 'NESTED' do
    gem 'nested-env'
  end
end
install_if true do
  gem 'always'
end
install_if false do
  gem 'never'
end
gem 'inline-if', install_if: nil
gem 'dev-typed', type: :development
gem 'run-typed', type: :runtime
